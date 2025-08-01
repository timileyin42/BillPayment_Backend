from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from ..core.database import Base

class Transaction(Base):
    __tablename__ = "transactions"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    biller_id = Column(Integer, ForeignKey("billers.id"), nullable=False)
    transaction_reference = Column(String, unique=True, index=True, nullable=False)
    bill_type = Column(String, nullable=False)  # 'electricity', 'water', 'internet', 'airtime'
    bill_amount = Column(Float, nullable=False)
    transaction_fee = Column(Float, default=0.0)
    total_amount = Column(Float, nullable=False)  # bill_amount + transaction_fee
    cashback_amount = Column(Float, default=0.0)
    cashback_rate = Column(Float, default=0.0)
    
    # Bill-specific details
    account_number = Column(String, nullable=False)  # meter number, phone number, etc.
    customer_name = Column(String, nullable=True)
    bill_details = Column(Text, nullable=True)  # JSON string for additional details
    
    # Transaction status and processing
    status = Column(String, default="pending")  # 'pending', 'processing', 'completed', 'failed', 'refunded'
    payment_status = Column(String, default="pending")  # 'pending', 'paid', 'failed'
    external_reference = Column(String, nullable=True)  # Biller's transaction reference
    failure_reason = Column(String, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="transactions")
    biller = relationship("Biller", back_populates="transactions")
    cashback_record = relationship("Cashback", back_populates="transaction", uselist=False)
    
    def __repr__(self):
        return f"<Transaction(id={self.id}, ref={self.transaction_reference}, status={self.status})>"

class RecurringPayment(Base):
    __tablename__ = "recurring_payments"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    biller_id = Column(Integer, ForeignKey("billers.id"), nullable=False)
    bill_type = Column(String, nullable=False)
    account_number = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    frequency = Column(String, nullable=False)  # 'weekly', 'monthly', 'quarterly'
    next_payment_date = Column(DateTime(timezone=True), nullable=False)
    is_active = Column(Boolean, default=True)
    auto_pay_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    def __repr__(self):
        return f"<RecurringPayment(id={self.id}, user_id={self.user_id}, frequency={self.frequency})>"