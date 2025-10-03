from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func, desc
from sqlalchemy.orm import selectinload

from ..database_model.archived_transaction import ArchivedTransaction
from ..database_model.transaction import Transaction
from ..core.database import AsyncSessionLocal


class ArchiveService:
    """Service for managing archived transactions."""
    
    @staticmethod
    async def archive_transaction(
        db: AsyncSession, 
        transaction: Transaction, 
        reason: str = "manual",
        retention_days: int = 2555
    ) -> ArchivedTransaction:
        """Archive a single transaction."""
        # Load related data if not already loaded
        if not hasattr(transaction, 'user') or transaction.user is None:
            await db.refresh(transaction, ['user'])
        if not hasattr(transaction, 'biller') or transaction.biller is None:
            await db.refresh(transaction, ['biller'])
        
        # Create archived transaction
        archived_transaction = ArchivedTransaction.from_transaction(
            transaction, 
            archived_reason=reason,
            retention_days=retention_days
        )
        
        # Add to database
        db.add(archived_transaction)
        
        # Delete original transaction
        await db.delete(transaction)
        
        return archived_transaction
    
    @staticmethod
    async def get_archived_transactions(
        user_id: Optional[int] = None,
        bill_type: Optional[str] = None,
        status: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[ArchivedTransaction]:
        """Retrieve archived transactions with filtering."""
        async with AsyncSessionLocal() as db:
            query = select(ArchivedTransaction)
            
            # Apply filters
            conditions = []
            if user_id:
                conditions.append(ArchivedTransaction.user_id == user_id)
            if bill_type:
                conditions.append(ArchivedTransaction.bill_type == bill_type)
            if status:
                conditions.append(ArchivedTransaction.status == status)
            if start_date:
                conditions.append(ArchivedTransaction.original_created_at >= start_date)
            if end_date:
                conditions.append(ArchivedTransaction.original_created_at <= end_date)
            
            if conditions:
                query = query.where(and_(*conditions))
            
            # Order by original creation date (newest first)
            query = query.order_by(desc(ArchivedTransaction.original_created_at))
            
            # Apply pagination
            query = query.offset(offset).limit(limit)
            
            result = await db.execute(query)
            return result.scalars().all()
    
    @staticmethod
    async def get_archive_statistics() -> Dict[str, Any]:
        """Get statistics about archived transactions."""
        async with AsyncSessionLocal() as db:
            # Total archived transactions
            total_result = await db.execute(
                select(func.count(ArchivedTransaction.id))
            )
            total_archived = total_result.scalar()
            
            # Archived by status
            status_result = await db.execute(
                select(
                    ArchivedTransaction.status,
                    func.count(ArchivedTransaction.id)
                ).group_by(ArchivedTransaction.status)
            )
            status_breakdown = {row[0]: row[1] for row in status_result.fetchall()}
            
            # Archived by bill type
            bill_type_result = await db.execute(
                select(
                    ArchivedTransaction.bill_type,
                    func.count(ArchivedTransaction.id)
                ).group_by(ArchivedTransaction.bill_type)
            )
            bill_type_breakdown = {row[0]: row[1] for row in bill_type_result.fetchall()}
            
            # Archive reasons
            reason_result = await db.execute(
                select(
                    ArchivedTransaction.archived_reason,
                    func.count(ArchivedTransaction.id)
                ).group_by(ArchivedTransaction.archived_reason)
            )
            reason_breakdown = {row[0]: row[1] for row in reason_result.fetchall()}
            
            # Total amount archived
            amount_result = await db.execute(
                select(func.sum(ArchivedTransaction.total_amount))
            )
            total_amount = amount_result.scalar() or 0.0
            
            return {
                "total_archived_transactions": total_archived,
                "status_breakdown": status_breakdown,
                "bill_type_breakdown": bill_type_breakdown,
                "archive_reason_breakdown": reason_breakdown,
                "total_archived_amount": total_amount,
                "generated_at": datetime.utcnow().isoformat()
            }
    
    @staticmethod
    async def cleanup_expired_archives(retention_days: int = 2555) -> Dict[str, Any]:
        """Clean up archived transactions that have exceeded their retention period."""
        async with AsyncSessionLocal() as db:
            cutoff_date = datetime.utcnow()
            
            # Find archives that have exceeded retention
            result = await db.execute(
                select(ArchivedTransaction).where(
                    and_(
                        ArchivedTransaction.retention_until.isnot(None),
                        ArchivedTransaction.retention_until < cutoff_date
                    )
                )
            )
            
            expired_archives = result.scalars().all()
            
            # Delete expired archives
            deleted_count = 0
            for archive in expired_archives:
                await db.delete(archive)
                deleted_count += 1
            
            await db.commit()
            
            return {
                "deleted_archives": deleted_count,
                "cutoff_date": cutoff_date.isoformat(),
                "timestamp": datetime.utcnow().isoformat()
            }
    
    @staticmethod
    async def restore_transaction(archive_id: int) -> Optional[Transaction]:
        """Restore an archived transaction back to active transactions (if needed)."""
        async with AsyncSessionLocal() as db:
            # Get archived transaction
            result = await db.execute(
                select(ArchivedTransaction).where(ArchivedTransaction.id == archive_id)
            )
            archived_transaction = result.scalar_one_or_none()
            
            if not archived_transaction:
                return None
            
            # Create new transaction from archived data
            restored_transaction = Transaction(
                user_id=archived_transaction.user_id,
                biller_id=archived_transaction.biller_id,
                transaction_reference=f"{archived_transaction.transaction_reference}_RESTORED",
                bill_type=archived_transaction.bill_type,
                bill_amount=archived_transaction.bill_amount,
                transaction_fee=archived_transaction.transaction_fee,
                total_amount=archived_transaction.total_amount,
                cashback_amount=archived_transaction.cashback_amount,
                cashback_rate=archived_transaction.cashback_rate,
                account_number=archived_transaction.account_number,
                customer_name=archived_transaction.customer_name,
                bill_details=archived_transaction.bill_details,
                status="pending",  # Reset to pending for reprocessing
                payment_status="pending",
                external_reference=archived_transaction.external_reference,
                failure_reason=None  # Clear failure reason
            )
            
            db.add(restored_transaction)
            await db.commit()
            await db.refresh(restored_transaction)
            
            return restored_transaction