from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import selectinload
import secrets
import string

from ..database_model.user import User
from ..database_model.wallet import Wallet
from ..database_model.transaction import Transaction, RecurringPayment
from ..database_model.cashback import Cashback, ReferralReward
from ..core.security import verify_password, get_password_hash, create_access_token, create_refresh_token
from ..core.errors import (
    AuthenticationError, 
    AuthorizationError, 
    NotFoundError, 
    ValidationError,
    DuplicateError
)
from .wallet_service import WalletService
from .notification import NotificationService
from ..services.cashback_service import CashbackService

class UserService:
    """Service for managing user operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.wallet_service = WalletService(db)
        self.notification_service = NotificationService()
    
    async def create_user(
        self,
        email: str,
        phone_number: str,
        password: str,
        first_name: str,
        last_name: str,
        referral_code: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new user account."""
        
        # Check if user already exists
        existing_user = await self.get_user_by_email_or_phone(email, phone_number)
        if existing_user:
            if existing_user.email == email:
                raise DuplicateError("User with this email already exists")
            else:
                raise DuplicateError("User with this phone number already exists")
        
        # Validate referral code if provided
        referrer = None
        if referral_code:
            referrer = await self.get_user_by_referral_code(referral_code)
            if not referrer:
                raise ValidationError("Invalid referral code")
        
        # Generate unique referral code for new user
        user_referral_code = await self._generate_unique_referral_code()
        
        # Create user
        hashed_password = get_password_hash(password)
        user = User(
            email=email,
            phone_number=phone_number,
            hashed_password=hashed_password,
            first_name=first_name,
            last_name=last_name,
            referral_code=user_referral_code,
            referred_by_id=referrer.id if referrer else None
        )
        
        self.db.add(user)
        await self.db.flush()  # Get user ID
        
        # Create wallet for user
        await self.wallet_service.create_wallet(user.id)
        
        # Process referral reward if applicable
        if referrer:
            await self._process_referral_reward(referrer.id, user.id)
        
        await self.db.commit()
        
        # Send welcome notification
        await self._send_welcome_notification(user)
        
        return {
            "user_id": user.id,
            "email": user.email,
            "phone_number": user.phone_number,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "referral_code": user.referral_code,
            "created_at": user.created_at.isoformat()
        }
    
    async def authenticate_user(
        self,
        email_or_phone: str,
        password: str
    ) -> Dict[str, Any]:
        """Authenticate user and return tokens."""
        
        user = await self.get_user_by_email_or_phone(email_or_phone, email_or_phone)
        if not user:
            raise AuthenticationError("Invalid credentials")
        
        if not verify_password(password, user.hashed_password):
            raise AuthenticationError("Invalid credentials")
        
        if not user.is_active:
            raise AuthenticationError("Account is deactivated")
        
        # Update last login
        user.last_login = datetime.utcnow()
        await self.db.commit()
        
        # Generate tokens
        access_token = create_access_token(data={"sub": str(user.id)})
        refresh_token = create_refresh_token(data={"sub": str(user.id)})
        
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "email": user.email,
                "phone_number": user.phone_number,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "is_verified": user.is_verified,
                "is_admin": user.is_admin
            }
        }
    
    async def get_user_by_id(self, user_id: int) -> Optional[User]:
        """Get user by ID."""
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()
    
    async def get_user_by_email_or_phone(
        self,
        email: str,
        phone_number: str
    ) -> Optional[User]:
        """Get user by email or phone number."""
        result = await self.db.execute(
            select(User).where(
                or_(User.email == email, User.phone_number == phone_number)
            )
        )
        return result.scalar_one_or_none()
    
    async def get_user_by_referral_code(self, referral_code: str) -> Optional[User]:
        """Get user by referral code."""
        result = await self.db.execute(
            select(User).where(User.referral_code == referral_code)
        )
        return result.scalar_one_or_none()
    
    async def update_user_profile(
        self,
        user_id: int,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        email: Optional[str] = None,
        phone_number: Optional[str] = None
    ) -> Dict[str, Any]:
        """Update user profile information."""
        
        user = await self.get_user_by_id(user_id)
        if not user:
            raise NotFoundError("User not found")
        
        # Check for email/phone conflicts if updating
        if email and email != user.email:
            existing = await self.get_user_by_email_or_phone(email, "")
            if existing and existing.id != user_id:
                raise DuplicateError("Email already in use")
            user.email = email
            user.is_verified = False  # Require re-verification
        
        if phone_number and phone_number != user.phone_number:
            existing = await self.get_user_by_email_or_phone("", phone_number)
            if existing and existing.id != user_id:
                raise DuplicateError("Phone number already in use")
            user.phone_number = phone_number
            user.is_verified = False  # Require re-verification
        
        if first_name:
            user.first_name = first_name
        
        if last_name:
            user.last_name = last_name
        
        user.updated_at = datetime.utcnow()
        await self.db.commit()
        
        return {
            "user_id": user.id,
            "email": user.email,
            "phone_number": user.phone_number,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "is_verified": user.is_verified,
            "updated_at": user.updated_at.isoformat()
        }
    
    async def change_password(
        self,
        user_id: int,
        current_password: str,
        new_password: str
    ) -> bool:
        """Change user password."""
        
        user = await self.get_user_by_id(user_id)
        if not user:
            raise NotFoundError("User not found")
        
        if not verify_password(current_password, user.hashed_password):
            raise AuthenticationError("Current password is incorrect")
        
        user.hashed_password = get_password_hash(new_password)
        user.updated_at = datetime.utcnow()
        await self.db.commit()
        
        # Send notification
        await self.notification_service.send_sms(
            user.phone_number,
            "Your Vision Fintech password has been changed successfully.",
            f"PASSWORD_CHANGE_{user.id}"
        )
        
        return True
    
    async def verify_user(self, user_id: int) -> bool:
        """Mark user as verified."""
        
        user = await self.get_user_by_id(user_id)
        if not user:
            raise NotFoundError("User not found")
        
        user.is_verified = True
        user.updated_at = datetime.utcnow()
        await self.db.commit()
        
        return True
    
    async def deactivate_user(self, user_id: int) -> bool:
        """Deactivate user account."""
        
        user = await self.get_user_by_id(user_id)
        if not user:
            raise NotFoundError("User not found")
        
        user.is_active = False
        user.updated_at = datetime.utcnow()
        await self.db.commit()
        
        return True
    
    async def get_user_dashboard_data(self, user_id: int) -> Dict[str, Any]:
        """Get comprehensive dashboard data for user."""
        
        user = await self.get_user_by_id(user_id)
        if not user:
            raise NotFoundError("User not found")
        
        # Get wallet information
        wallet_info = await self.wallet_service.get_wallet(user_id)
        
        # Get recent transactions (last 10)
        recent_transactions_result = await self.db.execute(
            select(Transaction)
            .where(Transaction.user_id == user_id)
            .order_by(Transaction.created_at.desc())
            .limit(10)
            .options(selectinload(Transaction.biller))
        )
        recent_transactions = recent_transactions_result.scalars().all()
        
        # Get monthly spending stats
        current_month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        monthly_stats_result = await self.db.execute(
            select(
                func.count(Transaction.id).label("transaction_count"),
                func.sum(Transaction.bill_amount).label("total_spent"),
                func.sum(Transaction.cashback_amount).label("total_cashback")
            ).where(
                and_(
                    Transaction.user_id == user_id,
                    Transaction.created_at >= current_month_start,
                    Transaction.status == "completed"
                )
            )
        )
        monthly_stats = monthly_stats_result.first()
        
        # Get active recurring payments
        recurring_payments_result = await self.db.execute(
            select(RecurringPayment)
            .where(
                and_(
                    RecurringPayment.user_id == user_id,
                    RecurringPayment.is_active == True
                )
            )
            .options(selectinload(RecurringPayment.biller))
        )
        recurring_payments = recurring_payments_result.scalars().all()
        
        # Get total cashback earned
        total_cashback_result = await self.db.execute(
            select(func.sum(Cashback.cashback_amount)).where(
                and_(
                    Cashback.user_id == user_id,
                    Cashback.status == "credited"
                )
            )
        )
        total_cashback_earned = total_cashback_result.scalar() or 0.0
        
        # Get referral stats
        referral_count_result = await self.db.execute(
            select(func.count(User.id)).where(User.referred_by_id == user_id)
        )
        referral_count = referral_count_result.scalar() or 0
        
        referral_rewards_result = await self.db.execute(
            select(func.sum(ReferralReward.reward_amount)).where(
                and_(
                    ReferralReward.referrer_id == user_id,
                    ReferralReward.status == "credited"
                )
            )
        )
        total_referral_rewards = referral_rewards_result.scalar() or 0.0
        
        return {
            "user": {
                "id": user.id,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email": user.email,
                "phone_number": user.phone_number,
                "is_verified": user.is_verified,
                "referral_code": user.referral_code,
                "member_since": user.created_at.isoformat()
            },
            "wallet": wallet_info,
            "monthly_stats": {
                "transaction_count": monthly_stats.transaction_count or 0,
                "total_spent": float(monthly_stats.total_spent or 0),
                "total_cashback": float(monthly_stats.total_cashback or 0)
            },
            "recent_transactions": [
                {
                    "id": tx.id,
                    "transaction_reference": tx.transaction_reference,
                    "biller_name": tx.biller.name,
                    "bill_type": tx.bill_type,
                    "amount": float(tx.bill_amount),
                    "status": tx.status,
                    "cashback_amount": float(tx.cashback_amount or 0),
                    "created_at": tx.created_at.isoformat()
                }
                for tx in recent_transactions
            ],
            "recurring_payments": [
                {
                    "id": rp.id,
                    "biller_name": rp.biller.name,
                    "bill_type": rp.bill_type,
                    "amount": float(rp.amount),
                    "frequency": rp.frequency,
                    "next_payment_date": rp.next_payment_date.isoformat(),
                    "auto_pay_enabled": rp.auto_pay_enabled
                }
                for rp in recurring_payments
            ],
            "rewards": {
                "total_cashback_earned": float(total_cashback_earned),
                "referral_count": referral_count,
                "total_referral_rewards": float(total_referral_rewards)
            }
        }
    
    async def _generate_unique_referral_code(self) -> str:
        """Generate a unique referral code."""
        while True:
            # Generate 8-character alphanumeric code
            code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
            
            # Check if code already exists
            existing = await self.get_user_by_referral_code(code)
            if not existing:
                return code
    
    async def _process_referral_reward(self, referrer_id: int, referred_id: int):
        """Process referral reward for successful referral."""
        
        cashback_service = CashbackService(self.db)
        
        # Create referral reward record
        referral_reward = ReferralReward(
            referrer_id=referrer_id,
            referred_user_id=referred_id,
            reward_amount=500.0,  # ₦500 referral bonus
            reward_type="signup_bonus",
            status="credited"
        )
        
        self.db.add(referral_reward)
        
        # Credit cashback to referrer's wallet
        await cashback_service.credit_cashback(
            user_id=referrer_id,
            amount=500.0,
            source="referral",
            description=f"Referral bonus for inviting new user",
            reference=f"REF_{referred_id}"
        )
    
    async def _send_welcome_notification(self, user: User):
        """Send welcome notification to new user."""
        welcome_message = (
            f"Welcome to Vision Fintech, {user.first_name}! "
            f"Your account has been created successfully. "
            f"Start paying bills and earning cashback today!"
        )
        
        await self.notification_service.send_sms(
            user.phone_number,
            welcome_message,
            f"WELCOME_{user.id}"
        )
        
        # Send welcome email if email service is configured
        await self.notification_service.send_email(
            user.email,
            "Welcome to Vision Fintech!",
            f"Hi {user.first_name},\n\n{welcome_message}\n\nBest regards,\nVision Fintech Team",
            f"WELCOME_EMAIL_{user.id}"
        )