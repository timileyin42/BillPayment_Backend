from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from ..core.database import Base

class Biller(Base):
    __tablename__ = "billers"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)  # e.g., "IKEDC", "MTN", "DSTV"
    code = Column(String, unique=True, index=True, nullable=False)  # Unique identifier
    bill_type = Column(String, nullable=False)  # 'electricity', 'water', 'internet', 'airtime'
    category = Column(String, nullable=False)  # 'utility', 'telecom', 'entertainment'
    logo_url = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    
    # API Configuration
    api_endpoint = Column(String, nullable=True)
    api_key = Column(String, nullable=True)
    api_username = Column(String, nullable=True)
    api_password = Column(String, nullable=True)
    
    # Business Configuration
    is_active = Column(Boolean, default=True)
    is_featured = Column(Boolean, default=False)
    min_amount = Column(Float, default=100.0)
    max_amount = Column(Float, default=1000000.0)
    transaction_fee = Column(Float, default=10.0)
    cashback_rate = Column(Float, default=0.05)  # 5% default
    
    # Validation Configuration
    account_number_length = Column(Integer, nullable=True)
    account_number_pattern = Column(String, nullable=True)  # Regex pattern
    requires_customer_validation = Column(Boolean, default=True)
    
    # Processing Configuration
    processing_time_minutes = Column(Integer, default=5)
    supports_instant_payment = Column(Boolean, default=True)
    supports_recurring_payment = Column(Boolean, default=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    transactions = relationship("Transaction", back_populates="biller")
    
    def __repr__(self):
        return f"<Biller(id={self.id}, name={self.name}, type={self.bill_type})>"

class BillerStatus(Base):
    __tablename__ = "biller_status"
    
    id = Column(Integer, primary_key=True, index=True)
    biller_id = Column(Integer, nullable=False)
    status = Column(String, nullable=False)  # 'online', 'offline', 'maintenance'
    response_time_ms = Column(Integer, nullable=True)
    success_rate = Column(Float, nullable=True)  # Percentage
    last_checked = Column(DateTime(timezone=True), server_default=func.now())
    error_message = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    def __repr__(self):
        return f"<BillerStatus(biller_id={self.biller_id}, status={self.status})>"