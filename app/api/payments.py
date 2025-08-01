from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, validator
from datetime import datetime

from ..core.database import get_database_session
from ..core.errors import (
    NotFoundError,
    ValidationError,
    InsufficientFundsError,
    PaymentFailedError
)
from ..services.payment_service import PaymentService
from .auth import get_current_user

router = APIRouter(prefix="/payments", tags=["Payments"])

# Pydantic models for request/response
class PaymentRequest(BaseModel):
    biller_code: str
    account_number: str
    amount: float
    use_cashback: bool = False
    
    @validator('amount')
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError('Amount must be greater than 0')
        if v < 50:  # Minimum payment amount
            raise ValueError('Minimum payment amount is ₦50')
        if v > 1000000:  # Maximum payment amount
            raise ValueError('Maximum payment amount is ₦1,000,000')
        return round(v, 2)
    
    @validator('account_number')
    def validate_account_number(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('Account number is required')
        return v.strip()

class RecurringPaymentRequest(BaseModel):
    biller_code: str
    account_number: str
    amount: float
    frequency: str
    auto_pay_enabled: bool = True
    
    @validator('frequency')
    def validate_frequency(cls, v):
        allowed_frequencies = ['weekly', 'monthly', 'quarterly']
        if v not in allowed_frequencies:
            raise ValueError(f'Frequency must be one of: {", ".join(allowed_frequencies)}')
        return v
    
    @validator('amount')
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError('Amount must be greater than 0')
        if v < 50:
            raise ValueError('Minimum payment amount is ₦50')
        if v > 500000:  # Lower max for recurring
            raise ValueError('Maximum recurring payment amount is ₦500,000')
        return round(v, 2)

class CustomerValidationRequest(BaseModel):
    biller_code: str
    account_number: str

# Response models
class PaymentBreakdownResponse(BaseModel):
    bill_amount: float
    convenience_fee: float
    cashback_amount: float
    total_amount: float
    cashback_rate: float

class PaymentResponse(BaseModel):
    transaction_id: int
    transaction_reference: str
    biller_name: str
    account_number: str
    amount: float
    convenience_fee: float
    cashback_amount: float
    total_amount: float
    status: str
    created_at: str

class TransactionResponse(BaseModel):
    id: int
    transaction_reference: str
    biller_name: str
    bill_type: str
    account_number: str
    amount: float
    convenience_fee: float
    cashback_amount: float
    status: str
    payment_status: str
    created_at: str
    completed_at: str = None

class CustomerInfoResponse(BaseModel):
    account_number: str
    customer_name: str
    customer_address: str = None
    outstanding_balance: float = None
    due_date: str = None
    additional_info: Dict[str, Any] = {}

@router.post("/validate-customer", response_model=CustomerInfoResponse)
async def validate_customer(
    validation_data: CustomerValidationRequest,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_database_session)
):
    """Validate customer account with biller."""
    try:
        payment_service = PaymentService(db)
        
        customer_info = await payment_service.validate_customer(
            biller_code=validation_data.biller_code,
            account_number=validation_data.account_number
        )
        
        return CustomerInfoResponse(**customer_info)
        
    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Customer validation failed"
        )

@router.post("/calculate-breakdown", response_model=PaymentBreakdownResponse)
async def calculate_payment_breakdown(
    payment_data: PaymentRequest,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_database_session)
):
    """Calculate payment breakdown including fees and cashback."""
    try:
        payment_service = PaymentService(db)
        
        breakdown = await payment_service.calculate_payment_breakdown(
            biller_code=payment_data.biller_code,
            amount=payment_data.amount,
            user_id=current_user.id
        )
        
        return PaymentBreakdownResponse(**breakdown)
        
    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to calculate payment breakdown"
        )

@router.post("/process", response_model=PaymentResponse)
async def process_payment(
    payment_data: PaymentRequest,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_database_session)
):
    """Process bill payment."""
    try:
        payment_service = PaymentService(db)
        
        transaction = await payment_service.process_payment(
            user_id=current_user.id,
            biller_code=payment_data.biller_code,
            account_number=payment_data.account_number,
            amount=payment_data.amount,
            use_cashback=payment_data.use_cashback
        )
        
        return PaymentResponse(
            transaction_id=transaction.id,
            transaction_reference=transaction.transaction_reference,
            biller_name=transaction.biller.name,
            account_number=transaction.account_number,
            amount=float(transaction.bill_amount),
            convenience_fee=float(transaction.convenience_fee or 0),
            cashback_amount=float(transaction.cashback_amount or 0),
            total_amount=float(transaction.total_amount),
            status=transaction.status,
            created_at=transaction.created_at.isoformat()
        )
        
    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except InsufficientFundsError as e:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=str(e)
        )
    except PaymentFailedError as e:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=str(e)
        )
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Payment processing failed"
        )

@router.get("/history", response_model=List[TransactionResponse])
async def get_payment_history(
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_database_session),
    limit: int = Query(20, ge=1, le=100, description="Number of transactions to retrieve"),
    offset: int = Query(0, ge=0, description="Number of transactions to skip"),
    status: Optional[str] = Query(None, description="Filter by transaction status"),
    biller_code: Optional[str] = Query(None, description="Filter by biller code")
):
    """Get user payment history."""
    try:
        payment_service = PaymentService(db)
        
        transactions = await payment_service.get_transaction_history(
            user_id=current_user.id,
            limit=limit,
            offset=offset,
            status=status,
            biller_code=biller_code
        )
        
        return [
            TransactionResponse(
                id=tx.id,
                transaction_reference=tx.transaction_reference,
                biller_name=tx.biller.name,
                bill_type=tx.bill_type,
                account_number=tx.account_number,
                amount=float(tx.bill_amount),
                convenience_fee=float(tx.convenience_fee or 0),
                cashback_amount=float(tx.cashback_amount or 0),
                status=tx.status,
                payment_status=tx.payment_status,
                created_at=tx.created_at.isoformat(),
                completed_at=tx.completed_at.isoformat() if tx.completed_at else None
            )
            for tx in transactions
        ]
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve payment history"
        )

@router.get("/transaction/{transaction_ref}", response_model=TransactionResponse)
async def get_transaction_details(
    transaction_ref: str,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_database_session)
):
    """Get specific transaction details."""
    try:
        payment_service = PaymentService(db)
        
        transaction = await payment_service.get_transaction_by_reference(
            user_id=current_user.id,
            transaction_reference=transaction_ref
        )
        
        if not transaction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Transaction not found"
            )
        
        return TransactionResponse(
            id=transaction.id,
            transaction_reference=transaction.transaction_reference,
            biller_name=transaction.biller.name,
            bill_type=transaction.bill_type,
            account_number=transaction.account_number,
            amount=float(transaction.bill_amount),
            convenience_fee=float(transaction.convenience_fee or 0),
            cashback_amount=float(transaction.cashback_amount or 0),
            status=transaction.status,
            payment_status=transaction.payment_status,
            created_at=transaction.created_at.isoformat(),
            completed_at=transaction.completed_at.isoformat() if transaction.completed_at else None
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve transaction details"
        )

@router.post("/retry/{transaction_ref}", response_model=PaymentResponse)
async def retry_failed_payment(
    transaction_ref: str,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_database_session)
):
    """Retry a failed payment transaction."""
    try:
        payment_service = PaymentService(db)
        
        transaction = await payment_service.retry_transaction(
            user_id=current_user.id,
            transaction_reference=transaction_ref
        )
        
        return PaymentResponse(
            transaction_id=transaction.id,
            transaction_reference=transaction.transaction_reference,
            biller_name=transaction.biller.name,
            account_number=transaction.account_number,
            amount=float(transaction.bill_amount),
            convenience_fee=float(transaction.convenience_fee or 0),
            cashback_amount=float(transaction.cashback_amount or 0),
            total_amount=float(transaction.total_amount),
            status=transaction.status,
            created_at=transaction.created_at.isoformat()
        )
        
    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except InsufficientFundsError as e:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=str(e)
        )
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Payment retry failed"
        )

@router.post("/recurring", response_model=Dict[str, Any])
async def setup_recurring_payment(
    recurring_data: RecurringPaymentRequest,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_database_session)
):
    """Setup recurring payment."""
    try:
        from ..database_model.transaction import RecurringPayment
        from ..database_model.biller import Biller
        from sqlalchemy import select
        from datetime import datetime, timedelta
        
        # Get biller
        biller_result = await db.execute(
            select(Biller).where(Biller.code == recurring_data.biller_code)
        )
        biller = biller_result.scalar_one_or_none()
        
        if not biller:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Biller not found"
            )
        
        # Calculate next payment date
        next_payment_date = datetime.utcnow()
        if recurring_data.frequency == "weekly":
            next_payment_date += timedelta(weeks=1)
        elif recurring_data.frequency == "monthly":
            next_payment_date += timedelta(days=30)
        elif recurring_data.frequency == "quarterly":
            next_payment_date += timedelta(days=90)
        
        # Create recurring payment
        recurring_payment = RecurringPayment(
            user_id=current_user.id,
            biller_id=biller.id,
            bill_type=biller.bill_type,
            account_number=recurring_data.account_number,
            amount=recurring_data.amount,
            frequency=recurring_data.frequency,
            next_payment_date=next_payment_date,
            auto_pay_enabled=recurring_data.auto_pay_enabled
        )
        
        db.add(recurring_payment)
        await db.commit()
        await db.refresh(recurring_payment)
        
        return {
            "recurring_payment_id": recurring_payment.id,
            "biller_name": biller.name,
            "account_number": recurring_payment.account_number,
            "amount": float(recurring_payment.amount),
            "frequency": recurring_payment.frequency,
            "next_payment_date": recurring_payment.next_payment_date.isoformat(),
            "auto_pay_enabled": recurring_payment.auto_pay_enabled,
            "message": "Recurring payment setup successfully"
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to setup recurring payment"
        )

@router.get("/recurring", response_model=List[Dict[str, Any]])
async def get_recurring_payments(
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_database_session)
):
    """Get user's recurring payments."""
    try:
        from ..database_model.transaction import RecurringPayment
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        
        result = await db.execute(
            select(RecurringPayment)
            .where(RecurringPayment.user_id == current_user.id)
            .options(selectinload(RecurringPayment.biller))
            .order_by(RecurringPayment.created_at.desc())
        )
        
        recurring_payments = result.scalars().all()
        
        return [
            {
                "id": rp.id,
                "biller_name": rp.biller.name,
                "bill_type": rp.bill_type,
                "account_number": rp.account_number,
                "amount": float(rp.amount),
                "frequency": rp.frequency,
                "next_payment_date": rp.next_payment_date.isoformat(),
                "auto_pay_enabled": rp.auto_pay_enabled,
                "is_active": rp.is_active,
                "created_at": rp.created_at.isoformat()
            }
            for rp in recurring_payments
        ]
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve recurring payments"
        )