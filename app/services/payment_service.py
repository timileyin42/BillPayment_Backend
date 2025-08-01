import uuid
import json
from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from datetime import datetime

from ..database_model.user import User
from ..database_model.biller import Biller
from ..database_model.transaction import Transaction, RecurringPayment
from ..payment_model.provider_factory import BillerProviderFactory
from ..payment_model.abstract_biller import PaymentRequest, CustomerInfo
from ..core.errors import (
    NotFoundError, ValidationError, PaymentFailedError, 
    InsufficientFundsError, ExternalServiceError
)
from ..core.config import settings
from .wallet_service import WalletService
from .cashback_service import CashbackService

class PaymentService:
    """Service for processing bill payments."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.wallet_service = WalletService(db)
        self.cashback_service = CashbackService(db)
    
    async def get_biller_by_code(self, biller_code: str) -> Optional[Biller]:
        """Get biller by code."""
        result = await self.db.execute(
            select(Biller).where(Biller.code == biller_code)
        )
        return result.scalar_one_or_none()
    
    async def get_active_billers(self, bill_type: Optional[str] = None) -> List[Biller]:
        """Get all active billers, optionally filtered by bill type."""
        query = select(Biller).where(Biller.is_active == True)
        
        if bill_type:
            query = query.where(Biller.bill_type == bill_type)
        
        query = query.order_by(Biller.is_featured.desc(), Biller.name)
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def validate_customer(
        self,
        biller_code: str,
        account_number: str
    ) -> CustomerInfo:
        """Validate customer account with biller."""
        # Get biller from database
        biller = await self.get_biller_by_code(biller_code)
        if not biller:
            raise NotFoundError(f"Biller not found: {biller_code}")
        
        if not biller.is_active:
            raise ValidationError(f"Biller is currently unavailable: {biller.name}")
        
        # Create biller provider instance
        provider_config = {
            "name": biller.name,
            "api_endpoint": biller.api_endpoint,
            "api_key": biller.api_key,
            "api_username": biller.api_username,
            "api_password": biller.api_password,
            "transaction_fee": biller.transaction_fee,
            "min_amount": biller.min_amount,
            "max_amount": biller.max_amount
        }
        
        try:
            biller_provider = BillerProviderFactory.create_biller(
                biller_code, provider_config
            )
            
            # Validate customer with the provider
            customer_info = await biller_provider.validate_customer(account_number)
            return customer_info
            
        except Exception as e:
            if isinstance(e, (ValidationError, ExternalServiceError)):
                raise e
            raise ExternalServiceError(f"Customer validation failed: {str(e)}")
    
    async def calculate_payment_breakdown(
        self,
        biller_code: str,
        amount: float,
        user_id: int
    ) -> Dict[str, Any]:
        """Calculate payment breakdown including fees and cashback."""
        biller = await self.get_biller_by_code(biller_code)
        if not biller:
            raise NotFoundError(f"Biller not found: {biller_code}")
        
        # Validate amount
        if amount < biller.min_amount:
            raise ValidationError(f"Minimum amount is ₦{biller.min_amount:.2f}")
        
        if amount > biller.max_amount:
            raise ValidationError(f"Maximum amount is ₦{biller.max_amount:.2f}")
        
        # Calculate fees
        transaction_fee = biller.transaction_fee
        total_amount = amount + transaction_fee
        
        # Calculate cashback
        cashback_amount = await self.cashback_service.calculate_cashback(
            user_id, biller.id, amount
        )
        
        return {
            "bill_amount": amount,
            "transaction_fee": transaction_fee,
            "total_amount": total_amount,
            "cashback_amount": cashback_amount,
            "cashback_rate": biller.cashback_rate,
            "net_amount": total_amount - cashback_amount
        }
    
    async def process_payment(
        self,
        user_id: int,
        biller_code: str,
        account_number: str,
        amount: float,
        customer_name: Optional[str] = None,
        phone_number: Optional[str] = None,
        email: Optional[str] = None,
        use_cashback: bool = False
    ) -> Transaction:
        """Process a bill payment."""
        # Get biller
        biller = await self.get_biller_by_code(biller_code)
        if not biller:
            raise NotFoundError(f"Biller not found: {biller_code}")
        
        if not biller.is_active:
            raise ValidationError(f"Biller is currently unavailable: {biller.name}")
        
        # Calculate payment breakdown
        breakdown = await self.calculate_payment_breakdown(biller_code, amount, user_id)
        total_amount = breakdown["total_amount"]
        
        # Check wallet balance
        wallet_balance = await self.wallet_service.get_balance(user_id)
        available_balance = wallet_balance["balance"]
        if use_cashback:
            available_balance += wallet_balance["cashback_balance"]
        
        if available_balance < total_amount:
            raise InsufficientFundsError(
                f"Insufficient funds. Available: ₦{available_balance:.2f}, Required: ₦{total_amount:.2f}"
            )
        
        # Generate transaction reference
        transaction_reference = f"VIS_{uuid.uuid4().hex[:12].upper()}"
        
        # Create transaction record
        transaction = Transaction(
            user_id=user_id,
            biller_id=biller.id,
            transaction_reference=transaction_reference,
            bill_type=biller.bill_type,
            bill_amount=amount,
            transaction_fee=breakdown["transaction_fee"],
            total_amount=total_amount,
            cashback_amount=breakdown["cashback_amount"],
            cashback_rate=breakdown["cashback_rate"],
            account_number=account_number,
            customer_name=customer_name,
            status="pending",
            payment_status="pending"
        )
        
        self.db.add(transaction)
        await self.db.commit()
        await self.db.refresh(transaction)
        
        try:
            # Debit wallet first
            await self.wallet_service.debit_wallet(
                user_id,
                total_amount,
                f"Bill payment - {biller.name} ({account_number})",
                f"PAY_{transaction_reference}",
                use_cashback
            )
            
            # Update transaction status
            transaction.payment_status = "paid"
            transaction.status = "processing"
            
            # Process payment with biller
            await self._process_with_biller(transaction, biller)
            
            await self.db.commit()
            
            return transaction
            
        except Exception as e:
            # Rollback transaction status
            transaction.status = "failed"
            transaction.failure_reason = str(e)
            
            # Refund wallet if payment was debited
            if transaction.payment_status == "paid":
                await self.wallet_service.fund_wallet(
                    user_id,
                    total_amount,
                    "refund",
                    f"REFUND_{transaction_reference}",
                    f"Refund for failed payment - {transaction_reference}"
                )
                
                # Confirm the refund
                refund_transaction = await self.wallet_service.get_transaction_by_reference(
                    f"REFUND_{transaction_reference}"
                )
                if refund_transaction:
                    await self.wallet_service.confirm_funding(refund_transaction.id)
            
            await self.db.commit()
            raise PaymentFailedError(f"Payment failed: {str(e)}")
    
    async def _process_with_biller(self, transaction: Transaction, biller: Biller):
        """Process payment with the actual biller provider."""
        # Create biller provider instance
        provider_config = {
            "name": biller.name,
            "api_endpoint": biller.api_endpoint,
            "api_key": biller.api_key,
            "api_username": biller.api_username,
            "api_password": biller.api_password
        }
        
        biller_provider = BillerProviderFactory.create_biller(
            biller.code, provider_config
        )
        
        # Create payment request
        payment_request = PaymentRequest(
            account_number=transaction.account_number,
            amount=transaction.bill_amount,
            customer_name=transaction.customer_name,
            reference=transaction.transaction_reference,
            phone_number=None,  # Could be added to transaction model
            email=None  # Could be added to transaction model
        )
        
        # Process payment
        payment_response = await biller_provider.process_payment(payment_request)
        
        if payment_response.success:
            transaction.status = "completed"
            transaction.external_reference = payment_response.external_reference
            transaction.completed_at = datetime.utcnow()
            
            # Store additional details
            bill_details = {
                "receipt_number": payment_response.receipt_number,
                "units_purchased": payment_response.units_purchased,
                "token": payment_response.token,
                "message": payment_response.message
            }
            transaction.bill_details = json.dumps(bill_details)
            
            # Process cashback
            if transaction.cashback_amount > 0:
                await self.cashback_service.credit_cashback(
                    transaction.user_id,
                    transaction.id,
                    transaction.cashback_amount,
                    transaction.bill_amount,
                    transaction.cashback_rate
                )
        else:
            transaction.status = "failed"
            transaction.failure_reason = payment_response.message
            raise PaymentFailedError(payment_response.message)
    
    async def get_transaction_by_reference(self, reference: str) -> Optional[Transaction]:
        """Get transaction by reference."""
        result = await self.db.execute(
            select(Transaction)
            .options(selectinload(Transaction.biller))
            .where(Transaction.transaction_reference == reference)
        )
        return result.scalar_one_or_none()
    
    async def get_user_transactions(
        self,
        user_id: int,
        limit: int = 50,
        offset: int = 0,
        bill_type: Optional[str] = None,
        status: Optional[str] = None
    ) -> List[Transaction]:
        """Get transaction history for a user."""
        query = select(Transaction).options(selectinload(Transaction.biller))
        query = query.where(Transaction.user_id == user_id)
        
        if bill_type:
            query = query.where(Transaction.bill_type == bill_type)
        
        if status:
            query = query.where(Transaction.status == status)
        
        query = query.order_by(Transaction.created_at.desc())
        query = query.offset(offset).limit(limit)
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def retry_failed_transaction(self, transaction_id: int) -> Transaction:
        """Retry a failed transaction."""
        result = await self.db.execute(
            select(Transaction)
            .options(selectinload(Transaction.biller))
            .where(Transaction.id == transaction_id)
        )
        transaction = result.scalar_one_or_none()
        
        if not transaction:
            raise NotFoundError("Transaction not found")
        
        if transaction.status != "failed":
            raise ValidationError("Only failed transactions can be retried")
        
        # Reset transaction status
        transaction.status = "processing"
        transaction.failure_reason = None
        
        try:
            # Process with biller again
            await self._process_with_biller(transaction, transaction.biller)
            await self.db.commit()
            return transaction
            
        except Exception as e:
            transaction.status = "failed"
            transaction.failure_reason = str(e)
            await self.db.commit()
            raise PaymentFailedError(f"Retry failed: {str(e)}")
    
    async def check_transaction_status(self, transaction_id: int) -> Dict[str, Any]:
        """Check transaction status with biller."""
        result = await self.db.execute(
            select(Transaction)
            .options(selectinload(Transaction.biller))
            .where(Transaction.id == transaction_id)
        )
        transaction = result.scalar_one_or_none()
        
        if not transaction:
            raise NotFoundError("Transaction not found")
        
        # Create biller provider instance
        biller = transaction.biller
        provider_config = {
            "name": biller.name,
            "api_endpoint": biller.api_endpoint,
            "api_key": biller.api_key,
            "api_username": biller.api_username,
            "api_password": biller.api_password
        }
        
        biller_provider = BillerProviderFactory.create_biller(
            biller.code, provider_config
        )
        
        # Check status with biller
        status_info = await biller_provider.check_transaction_status(
            transaction.transaction_reference
        )
        
        return {
            "transaction_id": transaction.id,
            "reference": transaction.transaction_reference,
            "local_status": transaction.status,
            "biller_status": status_info
        }