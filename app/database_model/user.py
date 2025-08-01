from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from ..core.database import Base

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    phone_number = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
    referral_code = Column(String, unique=True, index=True)
    referred_by = Column(String, nullable=True)  # referral code of referrer
    total_cashback_earned = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    wallet = relationship("Wallet", back_populates="user", uselist=False)
    transactions = relationship("Transaction", back_populates="user")
    cashback_records = relationship("Cashback", back_populates="user")
    
    def __repr__(self):
        return f"<User(id={self.id}, email={self.email}, phone={self.phone_number})>"