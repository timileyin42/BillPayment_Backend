from typing import List, Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.core.database import get_db
from app.core.security import get_current_user
from app.database_model.user import User
from app.database_model.cashback import Cashback, CashbackRule, ReferralReward
from app.services.cashback_service import CashbackService
from app.core.errors import NotFoundError, ValidationError

router = APIRouter(prefix="/api/v1/cashback", tags=["cashback"])


# Pydantic Models
class CashbackResponse(BaseModel):
    id: int
    user_id: int
    transaction_id: Optional[int]
    amount: float
    cashback_type: str
    description: str
    status: str
    created_at: datetime
    credited_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class CashbackSummaryResponse(BaseModel):
    total_earned: float
    total_pending: float
    total_credited: float
    this_month_earned: float
    cashback_count: int
    average_cashback: float
    recent_cashbacks: List[CashbackResponse]


class CashbackRuleResponse(BaseModel):
    id: int
    name: str
    description: str
    cashback_percentage: float
    min_amount: Optional[float]
    max_amount: Optional[float]
    max_cashback_per_transaction: Optional[float]
    max_cashback_per_month: Optional[float]
    bill_type: Optional[str]
    biller_code: Optional[str]
    is_active: bool
    priority: int
    
    class Config:
        from_attributes = True


class ReferralRewardResponse(BaseModel):
    id: int
    referrer_id: int
    referred_user_id: int
    reward_amount: float
    status: str
    created_at: datetime
    credited_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class ReferralSummaryResponse(BaseModel):
    total_referrals: int
    total_rewards_earned: float
    pending_rewards: float
    credited_rewards: float
    recent_referrals: List[ReferralRewardResponse]


@router.get("/history", response_model=List[CashbackResponse])
async def get_cashback_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    cashback_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None)
):
    """Get user's cashback history with filtering options."""
    cashback_service = CashbackService(db)
    
    try:
        cashbacks = await cashback_service.get_user_cashback_history(
            user_id=current_user.id,
            limit=limit,
            offset=offset,
            cashback_type=cashback_type,
            status=status,
            start_date=start_date,
            end_date=end_date
        )
        return cashbacks
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary", response_model=CashbackSummaryResponse)
async def get_cashback_summary(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user's cashback summary and statistics."""
    cashback_service = CashbackService(db)
    
    try:
        summary = await cashback_service.get_user_cashback_summary(current_user.id)
        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rules", response_model=List[CashbackRuleResponse])
async def get_active_cashback_rules(
    db: AsyncSession = Depends(get_db),
    bill_type: Optional[str] = Query(None),
    biller_code: Optional[str] = Query(None)
):
    """Get active cashback rules, optionally filtered by bill type or biller."""
    cashback_service = CashbackService(db)
    
    try:
        rules = await cashback_service.get_active_cashback_rules(
            bill_type=bill_type,
            biller_code=biller_code
        )
        return rules
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/calculate")
async def calculate_cashback(
    amount: float = Query(..., gt=0),
    bill_type: str = Query(...),
    biller_code: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Calculate potential cashback for a payment amount."""
    cashback_service = CashbackService(db)
    
    try:
        cashback_amount = await cashback_service.calculate_cashback(
            user_id=current_user.id,
            amount=amount,
            bill_type=bill_type,
            biller_code=biller_code
        )
        
        return {
            "amount": amount,
            "bill_type": bill_type,
            "biller_code": biller_code,
            "cashback_amount": cashback_amount,
            "cashback_percentage": (cashback_amount / amount * 100) if amount > 0 else 0
        }
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/referrals", response_model=ReferralSummaryResponse)
async def get_referral_summary(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user's referral rewards summary."""
    cashback_service = CashbackService(db)
    
    try:
        summary = await cashback_service.get_user_referral_summary(current_user.id)
        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/referrals/history", response_model=List[ReferralRewardResponse])
async def get_referral_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    """Get user's referral reward history."""
    cashback_service = CashbackService(db)
    
    try:
        referrals = await cashback_service.get_user_referral_history(
            user_id=current_user.id,
            limit=limit,
            offset=offset
        )
        return referrals
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/claim/{cashback_id}")
async def claim_cashback(
    cashback_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Claim a pending cashback reward."""
    cashback_service = CashbackService(db)
    
    try:
        result = await cashback_service.claim_cashback(
            cashback_id=cashback_id,
            user_id=current_user.id
        )
        
        if result:
            return {"message": "Cashback claimed successfully", "cashback_id": cashback_id}
        else:
            raise HTTPException(status_code=400, detail="Cashback cannot be claimed")
            
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Cashback not found")
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/leaderboard")
async def get_cashback_leaderboard(
    db: AsyncSession = Depends(get_db),
    period: str = Query("month", regex="^(week|month|year|all)$"),
    limit: int = Query(10, ge=1, le=50)
):
    """Get cashback leaderboard for the specified period."""
    cashback_service = CashbackService(db)
    
    try:
        leaderboard = await cashback_service.get_cashback_leaderboard(
            period=period,
            limit=limit
        )
        return leaderboard
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_cashback_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get detailed cashback statistics for the user."""
    cashback_service = CashbackService(db)
    
    try:
        stats = await cashback_service.get_user_cashback_stats(current_user.id)
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))