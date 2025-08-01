from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, validator
from decimal import Decimal
from datetime import datetime

from ..core.database import get_database_session
from ..core.errors import (
    NotFoundError,
    ValidationError,
    InsufficientFundsError,
    PaymentFailedError
)
from ..services.wallet_service import WalletService
from .auth import get_current_user

router = APIRouter(prefix="/wallet", tags=["Wallet"])

# Pydantic models for request/response
class WalletFundingRequest(BaseModel):
    amount: float
    payment_method: str
    payment_reference: str = None
    
    @validator('amount')
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError('Amount must be greater than 0')
        if v < 100:  # Minimum funding amount
            raise ValueError('Minimum funding amount is ₦100')
        if v > 1000000:  # Maximum funding amount
            raise ValueError('Maximum funding amount is ₦1,000,000')
        return round(v, 2)
    
    @validator('payment_method')
    def validate_payment_method(cls, v):
        allowed_methods = ['card', 'bank_transfer', 'ussd', 'bank_deposit']
        if v not in allowed_methods:
            raise ValueError(f'Payment method must be one of: {", ".join(allowed_methods)}')
        return v

class WalletTransferRequest(BaseModel):
    recipient_phone: str
    amount: float
    description: str = None
    
    @validator('amount')
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError('Amount must be greater than 0')
        if v < 50:  # Minimum transfer amount
            raise ValueError('Minimum transfer amount is ₦50')
        if v > 500000:  # Maximum transfer amount
            raise ValueError('Maximum transfer amount is ₦500,000')
        return round(v, 2)

class FundingConfirmationRequest(BaseModel):
    transaction_reference: str
    external_reference: str
    status: str
    
    @validator('status')
    def validate_status(cls, v):
        allowed_statuses = ['successful', 'failed', 'pending']
        if v not in allowed_statuses:
            raise ValueError(f'Status must be one of: {", ".join(allowed_statuses)}')
        return v

# Response models
class WalletResponse(BaseModel):
    user_id: int
    balance: float
    cashback_balance: float
    total_balance: float
    total_funded: float
    total_spent: float
    created_at: str
    updated_at: str

class WalletTransactionResponse(BaseModel):
    id: int
    transaction_type: str
    amount: float
    description: str
    reference: str
    payment_method: str
    status: str
    created_at: str

class FundingResponse(BaseModel):
    transaction_reference: str
    amount: float
    payment_method: str
    status: str
    message: str
    payment_url: str = None

class TransferResponse(BaseModel):
    transaction_reference: str
    sender_id: int
    recipient_id: int
    amount: float
    description: str
    status: str
    created_at: str

@router.get("/balance", response_model=WalletResponse)
async def get_wallet_balance(
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_database_session)
):
    """Get user wallet balance and information."""
    try:
        wallet_service = WalletService(db)
        wallet_info = await wallet_service.get_wallet(current_user.id)
        
        return WalletResponse(**wallet_info)
        
    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve wallet information"
        )

@router.post("/fund", response_model=FundingResponse)
async def fund_wallet(
    funding_data: WalletFundingRequest,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_database_session)
):
    """Initiate wallet funding."""
    try:
        wallet_service = WalletService(db)
        
        result = await wallet_service.fund_wallet(
            user_id=current_user.id,
            amount=funding_data.amount,
            payment_method=funding_data.payment_method,
            payment_reference=funding_data.payment_reference
        )
        
        return FundingResponse(
            transaction_reference=result["transaction_reference"],
            amount=result["amount"],
            payment_method=result["payment_method"],
            status=result["status"],
            message="Funding initiated successfully",
            payment_url=result.get("payment_url")
        )
        
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except PaymentFailedError as e:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Wallet funding failed"
        )

@router.post("/confirm-funding", response_model=Dict[str, Any])
async def confirm_wallet_funding(
    confirmation_data: FundingConfirmationRequest,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_database_session)
):
    """Confirm wallet funding transaction."""
    try:
        wallet_service = WalletService(db)
        
        result = await wallet_service.confirm_funding(
            user_id=current_user.id,
            transaction_reference=confirmation_data.transaction_reference,
            external_reference=confirmation_data.external_reference,
            status=confirmation_data.status
        )
        
        return {
            "message": "Funding confirmation processed successfully",
            "transaction_reference": result["transaction_reference"],
            "status": result["status"],
            "amount": result["amount"],
            "new_balance": result["new_balance"]
        }
        
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
            detail="Funding confirmation failed"
        )

@router.post("/transfer", response_model=TransferResponse)
async def transfer_funds(
    transfer_data: WalletTransferRequest,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_database_session)
):
    """Transfer funds to another user."""
    try:
        wallet_service = WalletService(db)
        
        result = await wallet_service.transfer_funds(
            sender_id=current_user.id,
            recipient_phone=transfer_data.recipient_phone,
            amount=transfer_data.amount,
            description=transfer_data.description or "Wallet transfer"
        )
        
        return TransferResponse(**result)
        
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
            detail="Fund transfer failed"
        )

@router.get("/transactions", response_model=List[WalletTransactionResponse])
async def get_wallet_transactions(
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_database_session),
    limit: int = Query(20, ge=1, le=100, description="Number of transactions to retrieve"),
    offset: int = Query(0, ge=0, description="Number of transactions to skip"),
    transaction_type: Optional[str] = Query(None, description="Filter by transaction type")
):
    """Get user wallet transaction history."""
    try:
        wallet_service = WalletService(db)
        
        transactions = await wallet_service.get_transaction_history(
            user_id=current_user.id,
            limit=limit,
            offset=offset,
            transaction_type=transaction_type
        )
        
        return [
            WalletTransactionResponse(
                id=tx["id"],
                transaction_type=tx["transaction_type"],
                amount=tx["amount"],
                description=tx["description"],
                reference=tx["reference"],
                payment_method=tx["payment_method"],
                status=tx["status"],
                created_at=tx["created_at"]
            )
            for tx in transactions
        ]
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve transaction history"
        )

@router.get("/transaction/{reference}", response_model=WalletTransactionResponse)
async def get_transaction_by_reference(
    reference: str,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_database_session)
):
    """Get specific wallet transaction by reference."""
    try:
        wallet_service = WalletService(db)
        
        transaction = await wallet_service.get_transaction_by_reference(
            user_id=current_user.id,
            reference=reference
        )
        
        if not transaction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Transaction not found"
            )
        
        return WalletTransactionResponse(
            id=transaction["id"],
            transaction_type=transaction["transaction_type"],
            amount=transaction["amount"],
            description=transaction["description"],
            reference=transaction["reference"],
            payment_method=transaction["payment_method"],
            status=transaction["status"],
            created_at=transaction["created_at"]
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve transaction"
        )

@router.get("/summary", response_model=Dict[str, Any])
async def get_wallet_summary(
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_database_session)
):
    """Get wallet summary with statistics."""
    try:
        wallet_service = WalletService(db)
        
        # Get wallet info
        wallet_info = await wallet_service.get_wallet(current_user.id)
        
        # Get recent transactions
        recent_transactions = await wallet_service.get_transaction_history(
            user_id=current_user.id,
            limit=5
        )
        
        # Calculate monthly statistics
        from datetime import datetime, timedelta
        from sqlalchemy import select, func, and_
        from ..database_model.wallet import WalletTransaction
        
        current_month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        monthly_stats_result = await db.execute(
            select(
                func.count(WalletTransaction.id).label("transaction_count"),
                func.sum(
                    func.case(
                        (WalletTransaction.transaction_type == "credit", WalletTransaction.amount),
                        else_=0
                    )
                ).label("total_credited"),
                func.sum(
                    func.case(
                        (WalletTransaction.transaction_type == "debit", WalletTransaction.amount),
                        else_=0
                    )
                ).label("total_debited")
            ).select_from(
                WalletTransaction.__table__.join(
                    wallet_service.db.execute(
                        select(wallet_service.Wallet.id).where(
                            wallet_service.Wallet.user_id == current_user.id
                        )
                    ).scalar_subquery()
                )
            ).where(
                WalletTransaction.created_at >= current_month_start
            )
        )
        
        monthly_stats = monthly_stats_result.first()
        
        return {
            "wallet": wallet_info,
            "recent_transactions": recent_transactions,
            "monthly_stats": {
                "transaction_count": monthly_stats.transaction_count or 0,
                "total_credited": float(monthly_stats.total_credited or 0),
                "total_debited": float(monthly_stats.total_debited or 0),
                "net_change": float((monthly_stats.total_credited or 0) - (monthly_stats.total_debited or 0))
            }
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve wallet summary"
        )