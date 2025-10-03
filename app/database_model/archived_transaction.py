from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Index
from sqlalchemy.sql import func
from ..core.database import Base

class ArchivedTransaction(Base):
    __tablename__ = "archived_transactions"
    
    id = Column(Integer, primary_key=True, index=True)
    original_transaction_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    biller_id = Column(Integer, nullable=False)
    transaction_reference = Column(String, index=True, nullable=False)
    bill_type = Column(String, nullable=False, index=True)
    bill_amount = Column(Float, nullable=False)
    transaction_fee = Column(Float, default=0.0)
    total_amount = Column(Float, nullable=False)
    cashback_amount = Column(Float, default=0.0)
    cashback_rate = Column(Float, default=0.0)
    
    # Bill-specific details
    account_number = Column(String, nullable=False)
    customer_name = Column(String, nullable=True)
    bill_details = Column(Text, nullable=True)
    
    # Transaction status and processing (final states)
    status = Column(String, nullable=False, index=True)
    payment_status = Column(String, nullable=False)
    external_reference = Column(String, nullable=True)
    failure_reason = Column(String, nullable=True)
    
    # Original timestamps
    original_created_at = Column(DateTime(timezone=True), nullable=False)
    original_updated_at = Column(DateTime(timezone=True), nullable=True)
    original_completed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Archive metadata
    archived_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    archived_reason = Column(String, nullable=False)  # 'expired', 'cleanup', 'manual'
    retention_until = Column(DateTime(timezone=True), nullable=True)  # For data retention policies
    
    # Additional metadata for audit trail
    user_email = Column(String, nullable=True)  # Snapshot of user email at archive time
    biller_name = Column(String, nullable=True)  # Snapshot of biller name at archive time
    
    # Indexes for efficient querying
    __table_args__ = (
        Index('idx_archived_user_date', 'user_id', 'original_created_at'),
        Index('idx_archived_status_date', 'status', 'original_created_at'),
        Index('idx_archived_bill_type_date', 'bill_type', 'original_created_at'),
        Index('idx_archived_retention', 'retention_until'),
    )
    
    def __repr__(self):
        return f"<ArchivedTransaction(id={self.id}, original_id={self.original_transaction_id}, ref={self.transaction_reference})>"
    
    @classmethod
    def from_transaction(cls, transaction, archived_reason: str = "cleanup", retention_days: int = 2555):  # ~7 years default
        """Create an archived transaction from a regular transaction."""
        from datetime import datetime, timedelta
        
        return cls(
            original_transaction_id=transaction.id,
            user_id=transaction.user_id,
            biller_id=transaction.biller_id,
            transaction_reference=transaction.transaction_reference,
            bill_type=transaction.bill_type,
            bill_amount=transaction.bill_amount,
            transaction_fee=transaction.transaction_fee,
            total_amount=transaction.total_amount,
            cashback_amount=transaction.cashback_amount,
            cashback_rate=transaction.cashback_rate,
            account_number=transaction.account_number,
            customer_name=transaction.customer_name,
            bill_details=transaction.bill_details,
            status=transaction.status,
            payment_status=transaction.payment_status,
            external_reference=transaction.external_reference,
            failure_reason=transaction.failure_reason,
            original_created_at=transaction.created_at,
            original_updated_at=transaction.updated_at,
            original_completed_at=transaction.completed_at,
            archived_reason=archived_reason,
            retention_until=datetime.utcnow() + timedelta(days=retention_days),
            user_email=getattr(transaction.user, 'email', None) if hasattr(transaction, 'user') and transaction.user else None,
            biller_name=getattr(transaction.biller, 'name', None) if hasattr(transaction, 'biller') and transaction.biller else None,
        )