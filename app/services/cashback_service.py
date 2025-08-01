import uuid
from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload
from datetime import datetime, timedelta

from ..database_model.user import User
from ..database_model.cashback import Cashback, CashbackRule, ReferralReward
from ..database_model.transaction import Transaction
from ..core.errors import NotFoundError, ValidationError
from ..core.config import settings
from .wallet_service import WalletService

class CashbackService:
    """Service for managing cashback and rewards."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.wallet_service = WalletService(db)
    
    async def get_applicable_cashback_rate(
        self,
        user_id: int,
        biller_id: int,
        bill_type: str,
        amount: float
    ) -> float:
        """Get the applicable cashback rate for a transaction."""
        # Query for specific biller rules first, then general rules
        query = select(CashbackRule).where(
            and_(
                CashbackRule.is_active == True,
                or_(
                    CashbackRule.valid_until.is_(None),
                    CashbackRule.valid_until > datetime.utcnow()
                ),
                CashbackRule.min_amount <= amount,
                or_(
                    CashbackRule.max_amount.is_(None),
                    CashbackRule.max_amount >= amount
                )
            )
        ).order_by(
            # Prioritize specific biller rules over general ones
            CashbackRule.biller_id.desc().nulls_last(),
            # Then prioritize specific bill type rules
            CashbackRule.bill_type.desc().nulls_last(),
            # Finally, highest cashback rate
            CashbackRule.cashback_rate.desc()
        )
        
        result = await self.db.execute(query)
        rules = result.scalars().all()
        
        for rule in rules:
            # Check if rule applies to this biller
            if rule.biller_id and rule.biller_id != biller_id:
                continue
            
            # Check if rule applies to this bill type
            if rule.bill_type and rule.bill_type != bill_type:
                continue
            
            # Check daily/monthly limits
            if await self._check_cashback_limits(user_id, rule, amount):
                return rule.cashback_rate
        
        # Return default rate if no specific rules apply
        return settings.default_cashback_rate
    
    async def _check_cashback_limits(
        self,
        user_id: int,
        rule: CashbackRule,
        amount: float
    ) -> bool:
        """Check if cashback limits allow this transaction."""
        now = datetime.utcnow()
        
        # Check per-transaction limit
        if rule.max_cashback_per_transaction:
            potential_cashback = amount * rule.cashback_rate
            if potential_cashback > rule.max_cashback_per_transaction:
                return False
        
        # Check daily limit
        if rule.max_cashback_per_day:
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            today_cashback = await self._get_cashback_sum(
                user_id, today_start, now
            )
            potential_cashback = amount * rule.cashback_rate
            if today_cashback + potential_cashback > rule.max_cashback_per_day:
                return False
        
        # Check monthly limit
        if rule.max_cashback_per_month:
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            month_cashback = await self._get_cashback_sum(
                user_id, month_start, now
            )
            potential_cashback = amount * rule.cashback_rate
            if month_cashback + potential_cashback > rule.max_cashback_per_month:
                return False
        
        return True
    
    async def _get_cashback_sum(
        self,
        user_id: int,
        start_date: datetime,
        end_date: datetime
    ) -> float:
        """Get sum of cashback earned in a date range."""
        result = await self.db.execute(
            select(func.coalesce(func.sum(Cashback.cashback_amount), 0))
            .where(
                and_(
                    Cashback.user_id == user_id,
                    Cashback.status == "credited",
                    Cashback.created_at >= start_date,
                    Cashback.created_at <= end_date
                )
            )
        )
        return result.scalar() or 0.0
    
    async def calculate_cashback(
        self,
        user_id: int,
        biller_id: int,
        amount: float,
        bill_type: Optional[str] = None
    ) -> float:
        """Calculate cashback amount for a transaction."""
        if not bill_type:
            # Get bill type from biller if not provided
            from ..database_model.biller import Biller
            result = await self.db.execute(
                select(Biller.bill_type).where(Biller.id == biller_id)
            )
            bill_type = result.scalar()
        
        if not bill_type:
            return 0.0
        
        # Get applicable cashback rate
        rate = await self.get_applicable_cashback_rate(
            user_id, biller_id, bill_type, amount
        )
        
        # Calculate cashback amount
        cashback_amount = amount * rate
        
        # Apply any global maximum cashback per transaction
        max_cashback = getattr(settings, 'max_cashback_per_transaction', None)
        if max_cashback and cashback_amount > max_cashback:
            cashback_amount = max_cashback
        
        return round(cashback_amount, 2)
    
    async def credit_cashback(
        self,
        user_id: int,
        transaction_id: int,
        cashback_amount: float,
        bill_amount: float,
        cashback_rate: float
    ) -> Cashback:
        """Credit cashback to user's account."""
        if cashback_amount <= 0:
            raise ValidationError("Cashback amount must be greater than zero")
        
        # Create cashback record
        cashback = Cashback(
            user_id=user_id,
            transaction_id=transaction_id,
            cashback_amount=cashback_amount,
            cashback_rate=cashback_rate,
            bill_amount=bill_amount,
            cashback_type="transaction",
            status="pending"
        )
        
        self.db.add(cashback)
        await self.db.commit()
        await self.db.refresh(cashback)
        
        # Credit to wallet
        await self.wallet_service.add_cashback(
            user_id,
            cashback_amount,
            f"Cashback for transaction #{transaction_id}",
            f"CASHBACK_{cashback.id}"
        )
        
        # Update cashback status
        cashback.status = "credited"
        cashback.credited_at = datetime.utcnow()
        
        # Update user's total cashback earned
        await self.db.execute(
            select(User).where(User.id == user_id)
        )
        user_result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        user = user_result.scalar_one_or_none()
        if user:
            user.total_cashback_earned += cashback_amount
        
        await self.db.commit()
        await self.db.refresh(cashback)
        
        return cashback
    
    async def get_user_cashback_summary(
        self,
        user_id: int,
        period: str = "all"  # "today", "week", "month", "all"
    ) -> Dict[str, Any]:
        """Get cashback summary for a user."""
        now = datetime.utcnow()
        
        # Determine date range
        if period == "today":
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "week":
            start_date = now - timedelta(days=7)
        elif period == "month":
            start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            start_date = None
        
        # Build query
        query = select(
            func.count(Cashback.id).label("total_transactions"),
            func.coalesce(func.sum(Cashback.cashback_amount), 0).label("total_cashback"),
            func.coalesce(func.avg(Cashback.cashback_rate), 0).label("avg_rate")
        ).where(
            and_(
                Cashback.user_id == user_id,
                Cashback.status == "credited"
            )
        )
        
        if start_date:
            query = query.where(Cashback.created_at >= start_date)
        
        result = await self.db.execute(query)
        summary = result.first()
        
        # Get cashback by bill type
        bill_type_query = select(
            Transaction.bill_type,
            func.count(Cashback.id).label("count"),
            func.coalesce(func.sum(Cashback.cashback_amount), 0).label("amount")
        ).select_from(
            Cashback.__table__.join(Transaction.__table__)
        ).where(
            and_(
                Cashback.user_id == user_id,
                Cashback.status == "credited"
            )
        ).group_by(Transaction.bill_type)
        
        if start_date:
            bill_type_query = bill_type_query.where(Cashback.created_at >= start_date)
        
        bill_type_result = await self.db.execute(bill_type_query)
        bill_type_breakdown = {
            row.bill_type: {
                "count": row.count,
                "amount": float(row.amount)
            }
            for row in bill_type_result
        }
        
        return {
            "period": period,
            "total_transactions": summary.total_transactions,
            "total_cashback": float(summary.total_cashback),
            "average_rate": float(summary.avg_rate),
            "bill_type_breakdown": bill_type_breakdown
        }
    
    async def get_cashback_history(
        self,
        user_id: int,
        limit: int = 50,
        offset: int = 0,
        cashback_type: Optional[str] = None
    ) -> List[Cashback]:
        """Get cashback history for a user."""
        query = select(Cashback).options(
            selectinload(Cashback.transaction)
        ).where(Cashback.user_id == user_id)
        
        if cashback_type:
            query = query.where(Cashback.cashback_type == cashback_type)
        
        query = query.order_by(Cashback.created_at.desc())
        query = query.offset(offset).limit(limit)
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def process_referral_reward(
        self,
        referrer_id: int,
        referred_id: int,
        reward_amount: float = 500.0
    ) -> ReferralReward:
        """Process referral reward for successful referral."""
        # Check if reward already exists
        existing_reward = await self.db.execute(
            select(ReferralReward).where(
                and_(
                    ReferralReward.referrer_id == referrer_id,
                    ReferralReward.referred_id == referred_id
                )
            )
        )
        
        if existing_reward.scalar_one_or_none():
            raise ValidationError("Referral reward already processed")
        
        # Create referral reward record
        reward = ReferralReward(
            referrer_id=referrer_id,
            referred_id=referred_id,
            reward_amount=reward_amount,
            status="pending"
        )
        
        self.db.add(reward)
        await self.db.commit()
        await self.db.refresh(reward)
        
        # Credit reward to referrer's wallet
        await self.wallet_service.add_cashback(
            referrer_id,
            reward_amount,
            f"Referral reward for user #{referred_id}",
            f"REFERRAL_{reward.id}"
        )
        
        # Update reward status
        reward.status = "credited"
        reward.credited_at = datetime.utcnow()
        
        await self.db.commit()
        await self.db.refresh(reward)
        
        return reward
    
    async def create_cashback_rule(
        self,
        cashback_rate: float,
        biller_id: Optional[int] = None,
        bill_type: Optional[str] = None,
        min_amount: float = 0.0,
        max_amount: Optional[float] = None,
        max_cashback_per_transaction: Optional[float] = None,
        max_cashback_per_day: Optional[float] = None,
        max_cashback_per_month: Optional[float] = None,
        valid_until: Optional[datetime] = None
    ) -> CashbackRule:
        """Create a new cashback rule."""
        if not (0 <= cashback_rate <= 1):
            raise ValidationError("Cashback rate must be between 0 and 1")
        
        rule = CashbackRule(
            biller_id=biller_id,
            bill_type=bill_type,
            cashback_rate=cashback_rate,
            min_amount=min_amount,
            max_amount=max_amount,
            max_cashback_per_transaction=max_cashback_per_transaction,
            max_cashback_per_day=max_cashback_per_day,
            max_cashback_per_month=max_cashback_per_month,
            valid_until=valid_until
        )
        
        self.db.add(rule)
        await self.db.commit()
        await self.db.refresh(rule)
        
        return rule