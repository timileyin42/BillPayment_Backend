import uuid
from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from datetime import datetime

from ..database_model.user import User
from ..database_model.wallet import Wallet, WalletTransaction
from ..core.errors import NotFoundError, InsufficientFundsError, ValidationError
from ..core.config import settings

class WalletService:
    """Service for managing wallet operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_wallet_by_user_id(self, user_id: int) -> Optional[Wallet]:
        """Get wallet for a specific user."""
        result = await self.db.execute(
            select(Wallet).where(Wallet.user_id == user_id)
        )
        return result.scalar_one_or_none()
    
    async def create_wallet(self, user_id: int) -> Wallet:
        """Create a new wallet for a user."""
        # Check if wallet already exists
        existing_wallet = await self.get_wallet_by_user_id(user_id)
        if existing_wallet:
            return existing_wallet
        
        wallet = Wallet(
            user_id=user_id,
            balance=0.0,
            cashback_balance=0.0,
            total_funded=0.0,
            total_spent=0.0
        )
        
        self.db.add(wallet)
        await self.db.commit()
        await self.db.refresh(wallet)
        return wallet
    
    async def get_balance(self, user_id: int) -> Dict[str, float]:
        """Get wallet balance for a user."""
        wallet = await self.get_wallet_by_user_id(user_id)
        if not wallet:
            raise NotFoundError("Wallet not found")
        
        return {
            "balance": wallet.balance,
            "cashback_balance": wallet.cashback_balance,
            "total_balance": wallet.balance + wallet.cashback_balance,
            "total_funded": wallet.total_funded,
            "total_spent": wallet.total_spent
        }
    
    async def fund_wallet(
        self,
        user_id: int,
        amount: float,
        payment_method: str,
        external_reference: Optional[str] = None,
        description: Optional[str] = None
    ) -> WalletTransaction:
        """Fund user wallet."""
        if amount <= 0:
            raise ValidationError("Amount must be greater than zero")
        
        wallet = await self.get_wallet_by_user_id(user_id)
        if not wallet:
            wallet = await self.create_wallet(user_id)
        
        # Generate unique reference
        reference = f"FUND_{uuid.uuid4().hex[:12].upper()}"
        
        # Create wallet transaction record
        transaction = WalletTransaction(
            wallet_id=wallet.id,
            transaction_type="credit",
            amount=amount,
            description=description or f"Wallet funding via {payment_method}",
            reference=reference,
            payment_method=payment_method,
            external_reference=external_reference,
            status="pending"
        )
        
        self.db.add(transaction)
        await self.db.commit()
        await self.db.refresh(transaction)
        
        return transaction
    
    async def confirm_funding(
        self,
        transaction_id: int,
        external_reference: Optional[str] = None
    ) -> WalletTransaction:
        """Confirm a pending funding transaction."""
        # Get the transaction
        result = await self.db.execute(
            select(WalletTransaction)
            .options(selectinload(WalletTransaction.wallet))
            .where(WalletTransaction.id == transaction_id)
        )
        transaction = result.scalar_one_or_none()
        
        if not transaction:
            raise NotFoundError("Transaction not found")
        
        if transaction.status != "pending":
            raise ValidationError(f"Transaction already {transaction.status}")
        
        # Update wallet balance
        wallet = transaction.wallet
        wallet.balance += transaction.amount
        wallet.total_funded += transaction.amount
        
        # Update transaction status
        transaction.status = "completed"
        if external_reference:
            transaction.external_reference = external_reference
        
        await self.db.commit()
        await self.db.refresh(transaction)
        
        return transaction
    
    async def debit_wallet(
        self,
        user_id: int,
        amount: float,
        description: str,
        reference: Optional[str] = None,
        use_cashback: bool = False
    ) -> WalletTransaction:
        """Debit amount from user wallet."""
        if amount <= 0:
            raise ValidationError("Amount must be greater than zero")
        
        wallet = await self.get_wallet_by_user_id(user_id)
        if not wallet:
            raise NotFoundError("Wallet not found")
        
        # Check available balance
        available_balance = wallet.balance
        if use_cashback:
            available_balance += wallet.cashback_balance
        
        if available_balance < amount:
            raise InsufficientFundsError(
                f"Insufficient funds. Available: ₦{available_balance:.2f}, Required: ₦{amount:.2f}"
            )
        
        # Generate reference if not provided
        if not reference:
            reference = f"DEBIT_{uuid.uuid4().hex[:12].upper()}"
        
        # Calculate how much to debit from each balance
        main_debit = min(amount, wallet.balance)
        cashback_debit = amount - main_debit if use_cashback else 0
        
        # Update wallet balances
        wallet.balance -= main_debit
        if cashback_debit > 0:
            wallet.cashback_balance -= cashback_debit
        wallet.total_spent += amount
        
        # Create transaction record
        transaction = WalletTransaction(
            wallet_id=wallet.id,
            transaction_type="debit",
            amount=amount,
            description=description,
            reference=reference,
            status="completed"
        )
        
        self.db.add(transaction)
        await self.db.commit()
        await self.db.refresh(transaction)
        
        return transaction
    
    async def add_cashback(
        self,
        user_id: int,
        amount: float,
        description: str,
        reference: Optional[str] = None
    ) -> WalletTransaction:
        """Add cashback to user wallet."""
        if amount <= 0:
            raise ValidationError("Cashback amount must be greater than zero")
        
        wallet = await self.get_wallet_by_user_id(user_id)
        if not wallet:
            wallet = await self.create_wallet(user_id)
        
        # Generate reference if not provided
        if not reference:
            reference = f"CASHBACK_{uuid.uuid4().hex[:12].upper()}"
        
        # Update cashback balance
        wallet.cashback_balance += amount
        
        # Create transaction record
        transaction = WalletTransaction(
            wallet_id=wallet.id,
            transaction_type="credit",
            amount=amount,
            description=description,
            reference=reference,
            payment_method="cashback",
            status="completed"
        )
        
        self.db.add(transaction)
        await self.db.commit()
        await self.db.refresh(transaction)
        
        return transaction
    
    async def get_transaction_history(
        self,
        user_id: int,
        limit: int = 50,
        offset: int = 0,
        transaction_type: Optional[str] = None
    ) -> List[WalletTransaction]:
        """Get wallet transaction history for a user."""
        wallet = await self.get_wallet_by_user_id(user_id)
        if not wallet:
            return []
        
        query = select(WalletTransaction).where(WalletTransaction.wallet_id == wallet.id)
        
        if transaction_type:
            query = query.where(WalletTransaction.transaction_type == transaction_type)
        
        query = query.order_by(WalletTransaction.created_at.desc())
        query = query.offset(offset).limit(limit)
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def get_transaction_by_reference(self, reference: str) -> Optional[WalletTransaction]:
        """Get transaction by reference."""
        result = await self.db.execute(
            select(WalletTransaction).where(WalletTransaction.reference == reference)
        )
        return result.scalar_one_or_none()
    
    async def transfer_between_wallets(
        self,
        from_user_id: int,
        to_user_id: int,
        amount: float,
        description: str
    ) -> Dict[str, WalletTransaction]:
        """Transfer funds between two wallets."""
        if amount <= 0:
            raise ValidationError("Transfer amount must be greater than zero")
        
        if from_user_id == to_user_id:
            raise ValidationError("Cannot transfer to the same wallet")
        
        # Generate transfer reference
        transfer_ref = f"TRANSFER_{uuid.uuid4().hex[:12].upper()}"
        
        # Debit from sender
        debit_transaction = await self.debit_wallet(
            from_user_id,
            amount,
            f"Transfer to user {to_user_id}: {description}",
            f"{transfer_ref}_OUT"
        )
        
        # Credit to receiver
        credit_transaction = await self.fund_wallet(
            to_user_id,
            amount,
            "transfer",
            f"{transfer_ref}_IN",
            f"Transfer from user {from_user_id}: {description}"
        )
        
        # Confirm the credit transaction
        await self.confirm_funding(credit_transaction.id)
        
        return {
            "debit_transaction": debit_transaction,
            "credit_transaction": credit_transaction
        }