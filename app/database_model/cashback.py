from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from ..core.database import Base

class Cashback(Base):
    __tablename__ = "cashbacks"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False)
    cashback_amount = Column(Float, nullable=False)
    cashback_rate = Column(Float, nullable=False)  # Rate used for calculation
    bill_amount = Column(Float, nullable=False)  # Original bill amount
    cashback_type = Column(String, default="transaction")  # 'transaction', 'referral', 'bonus'
    status = Column(String, default="pending")  # 'pending', 'credited', 'expired'
    credited_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)  # Cashback expiry
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="cashback_records")
    transaction = relationship("Transaction", back_populates="cashback_record")
    
    def __repr__(self):
        return f"<Cashback(id={self.id}, user_id={self.user_id}, amount={self.cashback_amount})>"

class CashbackRule(Base):
    __tablename__ = "cashback_rules"
    
    id = Column(Integer, primary_key=True, index=True)
    biller_id = Column(Integer, ForeignKey("billers.id"), nullable=True)  # Null for global rules
    bill_type = Column(String, nullable=True)  # Null for all bill types
    cashback_rate = Column(Float, nullable=False)
    min_amount = Column(Float, default=0.0)
    max_amount = Column(Float, nullable=True)
    max_cashback_per_transaction = Column(Float, nullable=True)
    max_cashback_per_day = Column(Float, nullable=True)
    max_cashback_per_month = Column(Float, nullable=True)
    is_active = Column(Boolean, default=True)
    valid_from = Column(DateTime(timezone=True), server_default=func.now())
    valid_until = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    def __repr__(self):
        return f"<CashbackRule(id={self.id}, rate={self.cashback_rate}, bill_type={self.bill_type})>"

class ReferralReward(Base):
    __tablename__ = "referral_rewards"
    
    id = Column(Integer, primary_key=True, index=True)
    referrer_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # User who referred
    referred_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # User who was referred
    reward_amount = Column(Float, default=500.0)  # ₦500 as mentioned in PRD
    status = Column(String, default="pending")  # 'pending', 'credited', 'expired'
    credited_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    def __repr__(self):
        return f"<ReferralReward(id={self.id}, referrer_id={self.referrer_id}, amount={self.reward_amount})>"