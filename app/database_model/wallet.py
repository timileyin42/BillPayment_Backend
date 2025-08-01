from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from ..core.database import Base

class Wallet(Base):
    __tablename__ = "wallets"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    balance = Column(Float, default=0.0, nullable=False)
    cashback_balance = Column(Float, default=0.0, nullable=False)
    total_funded = Column(Float, default=0.0, nullable=False)
    total_spent = Column(Float, default=0.0, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="wallet")
    funding_transactions = relationship("WalletTransaction", back_populates="wallet")
    
    def __repr__(self):
        return f"<Wallet(id={self.id}, user_id={self.user_id}, balance={self.balance})>"

class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"
    
    id = Column(Integer, primary_key=True, index=True)
    wallet_id = Column(Integer, ForeignKey("wallets.id"), nullable=False)
    transaction_type = Column(String, nullable=False)  # 'credit', 'debit'
    amount = Column(Float, nullable=False)
    description = Column(String, nullable=False)
    reference = Column(String, unique=True, index=True, nullable=False)
    payment_method = Column(String, nullable=True)  # 'bank_transfer', 'card', 'agent'
    external_reference = Column(String, nullable=True)  # Bank/payment gateway reference
    status = Column(String, default="pending")  # 'pending', 'completed', 'failed'
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    wallet = relationship("Wallet", back_populates="funding_transactions")
    
    def __repr__(self):
        return f"<WalletTransaction(id={self.id}, type={self.transaction_type}, amount={self.amount})>"