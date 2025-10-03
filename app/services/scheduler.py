import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import selectinload

from ..database_model.transaction import RecurringPayment
from ..database_model.user import User
from ..database_model.biller import Biller
from ..core.database import AsyncSessionLocal
from ..database_model.transaction import Transaction
from ..database_model.cashback import Cashback
from ..core.errors import PaymentFailedError, InsufficientFundsError
from .payment_service import PaymentService
from .wallet_service import WalletService
from .notification import NotificationService
from ..database_model.transaction import Transaction
from ..database_model.archived_transaction import ArchivedTransaction
from sqlalchemy.orm import selectinload

class SchedulerService:
    """Service for handling scheduled and recurring tasks."""
    
    def __init__(self):
        self.notification_service = NotificationService()
    
    async def process_recurring_payments(self) -> Dict[str, Any]:
        """Process all due recurring payments."""
        async with AsyncSessionLocal() as db:
            payment_service = PaymentService(db)
            wallet_service = WalletService(db)
            
            # Get all due recurring payments
            now = datetime.utcnow()
            
            result = await db.execute(
                select(RecurringPayment)
                .options(
                    selectinload(RecurringPayment.user),
                    selectinload(RecurringPayment.biller)
                )
                .where(
                    and_(
                        RecurringPayment.is_active == True,
                        RecurringPayment.auto_pay_enabled == True,
                        RecurringPayment.next_payment_date <= now
                    )
                )
            )
            
            recurring_payments = result.scalars().all()
            
            processed = 0
            successful = 0
            failed = 0
            errors = []
            
            for recurring_payment in recurring_payments:
                try:
                    # Check wallet balance
                    balance = await wallet_service.get_balance(recurring_payment.user_id)
                    
                    # Calculate total amount needed (including fees)
                    breakdown = await payment_service.calculate_payment_breakdown(
                        recurring_payment.biller.code,
                        recurring_payment.amount,
                        recurring_payment.user_id
                    )
                    
                    total_needed = breakdown["total_amount"]
                    
                    if balance["total_balance"] >= total_needed:
                        # Process the payment
                        transaction = await payment_service.process_payment(
                            user_id=recurring_payment.user_id,
                            biller_code=recurring_payment.biller.code,
                            account_number=recurring_payment.account_number,
                            amount=recurring_payment.amount,
                            use_cashback=True  # Use cashback for recurring payments
                        )
                        
                        # Update next payment date
                        await self._update_next_payment_date(db, recurring_payment)
                        
                        # Send notification
                        await self._send_recurring_payment_notification(
                            recurring_payment, transaction, successful=True
                        )
                        
                        successful += 1
                    else:
                        # Insufficient funds - notify user and optionally disable auto-pay
                        await self._handle_insufficient_funds(
                            db, recurring_payment, total_needed, balance["total_balance"]
                        )
                        failed += 1
                        errors.append({
                            "recurring_payment_id": recurring_payment.id,
                            "error": "Insufficient funds",
                            "required": total_needed,
                            "available": balance["total_balance"]
                        })
                    
                    processed += 1
                    
                except Exception as e:
                    failed += 1
                    errors.append({
                        "recurring_payment_id": recurring_payment.id,
                        "error": str(e)
                    })
                    
                    # Send failure notification
                    await self._send_recurring_payment_notification(
                        recurring_payment, None, successful=False, error=str(e)
                    )
            
            await db.commit()
            
            return {
                "processed": processed,
                "successful": successful,
                "failed": failed,
                "errors": errors,
                "timestamp": now.isoformat()
            }
    
    async def _update_next_payment_date(
        self,
        db: AsyncSession,
        recurring_payment: RecurringPayment
    ):
        """Update the next payment date based on frequency."""
        current_date = recurring_payment.next_payment_date
        
        if recurring_payment.frequency == "weekly":
            next_date = current_date + timedelta(weeks=1)
        elif recurring_payment.frequency == "monthly":
            # Add one month (handle month-end dates properly)
            if current_date.month == 12:
                next_date = current_date.replace(year=current_date.year + 1, month=1)
            else:
                next_date = current_date.replace(month=current_date.month + 1)
        elif recurring_payment.frequency == "quarterly":
            # Add three months
            month = current_date.month + 3
            year = current_date.year
            if month > 12:
                month -= 12
                year += 1
            next_date = current_date.replace(year=year, month=month)
        else:
            # Default to monthly
            next_date = current_date + timedelta(days=30)
        
        recurring_payment.next_payment_date = next_date
    
    async def _handle_insufficient_funds(
        self,
        db: AsyncSession,
        recurring_payment: RecurringPayment,
        required_amount: float,
        available_amount: float
    ):
        """Handle insufficient funds for recurring payment."""
        # Update next payment date to retry tomorrow
        recurring_payment.next_payment_date = datetime.utcnow() + timedelta(days=1)
        
        # Send notification about insufficient funds
        user = recurring_payment.user
        biller = recurring_payment.biller
        
        sms_message = (
            f"Recurring payment failed due to insufficient funds. "
            f"Required: ₦{required_amount:.2f}, Available: ₦{available_amount:.2f}. "
            f"Please fund your wallet. - Vision Fintech"
        )
        
        await self.notification_service.send_sms(
            user.phone_number,
            sms_message,
            f"RECURRING_FAIL_{recurring_payment.id}"
        )
    
    async def _send_recurring_payment_notification(
        self,
        recurring_payment: RecurringPayment,
        transaction: Optional[Any],
        successful: bool,
        error: Optional[str] = None
    ):
        """Send notification for recurring payment result."""
        user = recurring_payment.user
        biller = recurring_payment.biller
        
        if successful and transaction:
            # Success notification
            await self.notification_service.send_payment_confirmation(
                phone_number=user.phone_number,
                email=user.email,
                transaction_ref=transaction.transaction_reference,
                amount=transaction.bill_amount,
                biller_name=biller.name,
                account_number=transaction.account_number,
                cashback_amount=transaction.cashback_amount
            )
        else:
            # Failure notification
            sms_message = (
                f"Recurring payment to {biller.name} failed. "
                f"Amount: ₦{recurring_payment.amount:.2f}. "
                f"Reason: {error or 'Unknown error'}. - Vision Fintech"
            )
            
            await self.notification_service.send_sms(
                user.phone_number,
                sms_message,
                f"RECURRING_FAIL_{recurring_payment.id}"
            )
    
    async def cleanup_expired_transactions(self, days_old: int = 30, archive_only: bool = True) -> Dict[str, Any]:
        """Archive old failed/expired transactions instead of deleting them."""
        async with AsyncSessionLocal() as db:
            cutoff_date = datetime.utcnow() - timedelta(days=days_old)
            
            # Get expired transactions with related data for archiving
            
            result = await db.execute(
                select(Transaction)
                .options(selectinload(Transaction.user), selectinload(Transaction.biller))
                .where(
                    and_(
                        Transaction.status.in_(["failed", "expired"]),
                        Transaction.created_at < cutoff_date
                    )
                )
            )
            
            expired_transactions = result.scalars().all()
            
            archived_count = 0
            deleted_count = 0
            failed_count = 0
            
            for transaction in expired_transactions:
                try:
                    if archive_only:
                        # Create archived transaction
                        archived_transaction = ArchivedTransaction.from_transaction(
                            transaction, 
                            archived_reason="cleanup",
                            retention_days=2555  # ~7 years retention
                        )
                        
                        # Add to database
                        db.add(archived_transaction)
                        
                        # Delete original transaction
                        await db.delete(transaction)
                        archived_count += 1
                    else:
                        # Direct deletion (legacy behavior)
                        await db.delete(transaction)
                        deleted_count += 1
                        
                except Exception as e:
                    # Log the error but continue with other transactions
                    print(f"Failed to archive transaction {transaction.id}: {str(e)}")
                    failed_count += 1
                    continue
            
            await db.commit()
            
            return {
                "archived_transactions": archived_count,
                "deleted_transactions": deleted_count,
                "failed_transactions": failed_count,
                "cutoff_date": cutoff_date.isoformat(),
                "timestamp": datetime.utcnow().isoformat(),
                "archive_mode": archive_only
            }
    
    async def update_biller_status(self) -> Dict[str, Any]:
        """Update status of all billers by checking their health."""
        async with AsyncSessionLocal() as db:
            from ..database_model.biller import Biller, BillerStatus
            from ..payment_model.provider_factory import BillerProviderFactory
            
            # Get all active billers
            result = await db.execute(
                select(Biller).where(Biller.is_active == True)
            )
            billers = result.scalars().all()
            
            updated_count = 0
            status_updates = []
            
            for biller in billers:
                try:
                    # Create provider instance
                    provider_config = {
                        "name": biller.name,
                        "api_endpoint": biller.api_endpoint,
                        "api_key": biller.api_key,
                        "api_username": biller.api_username,
                        "api_password": biller.api_password
                    }
                    
                    provider = BillerProviderFactory.create_biller(
                        biller.code, provider_config
                    )
                    
                    # Check service status
                    start_time = datetime.utcnow()
                    status_info = await provider.get_service_status()
                    end_time = datetime.utcnow()
                    
                    response_time = int((end_time - start_time).total_seconds() * 1000)
                    
                    # Create status record
                    biller_status = BillerStatus(
                        biller_id=biller.id,
                        status=status_info.get("status", "unknown"),
                        response_time_ms=response_time,
                        last_checked=datetime.utcnow()
                    )
                    
                    db.add(biller_status)
                    updated_count += 1
                    
                    status_updates.append({
                        "biller_id": biller.id,
                        "biller_name": biller.name,
                        "status": biller_status.status,
                        "response_time_ms": response_time
                    })
                    
                except Exception as e:
                    # Record error status
                    biller_status = BillerStatus(
                        biller_id=biller.id,
                        status="error",
                        error_message=str(e),
                        last_checked=datetime.utcnow()
                    )
                    
                    db.add(biller_status)
                    
                    status_updates.append({
                        "biller_id": biller.id,
                        "biller_name": biller.name,
                        "status": "error",
                        "error": str(e)
                    })
            
            await db.commit()
            
            return {
                "updated_billers": updated_count,
                "status_updates": status_updates,
                "timestamp": datetime.utcnow().isoformat()
            }
    
    async def send_daily_summary_notifications(self) -> Dict[str, Any]:
        """Send daily summary notifications to users."""
        async with AsyncSessionLocal() as db:
            
            # Get users who had transactions today
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            today_end = today_start + timedelta(days=1)
            
            result = await db.execute(
                select(User.id, User.phone_number, User.email, User.first_name)
                .select_from(
                    User.__table__.join(Transaction.__table__)
                )
                .where(
                    and_(
                        Transaction.created_at >= today_start,
                        Transaction.created_at < today_end,
                        Transaction.status == "completed"
                    )
                )
                .distinct()
            )
            
            active_users = result.all()
            notifications_sent = 0
            
            for user in active_users:
                try:
                    # Get user's daily stats
                    transaction_result = await db.execute(
                        select(
                            func.count(Transaction.id).label("transaction_count"),
                            func.sum(Transaction.bill_amount).label("total_spent")
                        ).where(
                            and_(
                                Transaction.user_id == user.id,
                                Transaction.created_at >= today_start,
                                Transaction.created_at < today_end,
                                Transaction.status == "completed"
                            )
                        )
                    )
                    
                    transaction_stats = transaction_result.first()
                    
                    cashback_result = await db.execute(
                        select(func.sum(Cashback.cashback_amount)).where(
                            and_(
                                Cashback.user_id == user.id,
                                Cashback.created_at >= today_start,
                                Cashback.created_at < today_end,
                                Cashback.status == "credited"
                            )
                        )
                    )
                    
                    total_cashback = cashback_result.scalar() or 0.0
                    
                    # Send summary SMS
                    sms_message = (
                        f"Hi {user.first_name}! Today's summary: "
                        f"{transaction_stats.transaction_count} payments, "
                        f"₦{transaction_stats.total_spent:.2f} spent, "
                        f"₦{total_cashback:.2f} cashback earned. - Vision Fintech"
                    )
                    
                    await self.notification_service.send_sms(
                        user.phone_number,
                        sms_message,
                        f"DAILY_SUMMARY_{user.id}_{today_start.strftime('%Y%m%d')}"
                    )
                    
                    notifications_sent += 1
                    
                except Exception as e:
                    # Log error but continue with other users
                    continue
            
            return {
                "notifications_sent": notifications_sent,
                "active_users": len(active_users),
                "date": today_start.strftime('%Y-%m-%d'),
                "timestamp": datetime.utcnow().isoformat()
            }