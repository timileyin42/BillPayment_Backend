import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio

from app.core.database import AsyncSessionLocal
from app.database_model.transaction import RecurringPayment, RecurringPaymentStatus, Transaction
from app.database_model.wallet import Wallet
from app.database_model.user import User
from app.services.payment_service import PaymentService
from app.services.notification import NotificationService
from app.utils.lock_manager import acquire_lock, LockPatterns
from app.utils.webhooks import dispatch_event, EventTypes
from app.tasks import celery_app


logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.recurring_payments.process_recurring_payments")
def process_recurring_payments() -> Dict[str, Any]:
    """Process all due recurring payments.
    
    This task finds all active recurring payments that are due and processes them.
    It handles payment execution, status updates, and notifications.
    
    Returns:
        Dict[str, Any]: Summary of processed payments
    """
    logger.info("Starting recurring payments processing")
    
    # Use sync-to-async pattern for Celery compatibility
    return asyncio.run(_process_recurring_payments_async())


async def _process_recurring_payments_async() -> Dict[str, Any]:
    """Async implementation of recurring payments processing.
    
    Returns:
        Dict[str, Any]: Summary of processed payments
    """
    async with AsyncSessionLocal() as session:
        # Find all active recurring payments that are due
        due_payments = await _get_due_recurring_payments(session)
        
        logger.info(f"Found {len(due_payments)} due recurring payments")
        
        results = {
            "total": len(due_payments),
            "successful": 0,
            "failed": 0,
            "skipped": 0,
            "details": []
        }
        
        for payment in due_payments:
            try:
                # Process each payment with a distributed lock to prevent duplicates
                async with acquire_lock(LockPatterns.recurring_payment(payment.id), timeout=60.0):
                    result = await _process_single_recurring_payment(session, payment)
                    results["details"].append(result)
                    
                    if result["status"] == "success":
                        results["successful"] += 1
                    elif result["status"] == "failed":
                        results["failed"] += 1
                    else:
                        results["skipped"] += 1
            except Exception as e:
                logger.error(f"Error processing recurring payment {payment.id}: {str(e)}")
                results["failed"] += 1
                results["details"].append({
                    "id": payment.id,
                    "status": "failed",
                    "error": str(e)
                })
        
        return results


async def _get_due_recurring_payments(session: AsyncSession) -> List[RecurringPayment]:
    """Get all due recurring payments.
    
    Args:
        session: Database session
        
    Returns:
        List[RecurringPayment]: List of due recurring payments
    """
    now = datetime.utcnow()
    
    # Find all active recurring payments that are due
    query = select(RecurringPayment).where(
        RecurringPayment.status == RecurringPaymentStatus.ACTIVE,
        RecurringPayment.next_payment_date <= now
    )
    
    result = await session.execute(query)
    return result.scalars().all()


async def _process_single_recurring_payment(
    session: AsyncSession,
    payment: RecurringPayment
) -> Dict[str, Any]:
    """Process a single recurring payment.
    
    Args:
        session: Database session
        payment: Recurring payment to process
        
    Returns:
        Dict[str, Any]: Result of payment processing
    """
    logger.info(f"Processing recurring payment {payment.id} for user {payment.user_id}")
    
    # Get user and wallet
    user_query = select(User).where(User.id == payment.user_id)
    wallet_query = select(Wallet).where(Wallet.user_id == payment.user_id)
    
    user_result = await session.execute(user_query)
    wallet_result = await session.execute(wallet_query)
    
    user = user_result.scalar_one_or_none()
    wallet = wallet_result.scalar_one_or_none()
    
    if not user or not wallet:
        logger.error(f"User or wallet not found for recurring payment {payment.id}")
        await _update_recurring_payment_status(
            session, payment, RecurringPaymentStatus.ERROR,
            "User or wallet not found"
        )
        return {
            "id": payment.id,
            "status": "failed",
            "error": "User or wallet not found"
        }
    
    # Check if wallet has sufficient balance
    if wallet.balance < payment.amount:
        logger.warning(f"Insufficient balance for recurring payment {payment.id}")
        
        # Send low balance notification
        notification_service = NotificationService()
        await notification_service.send_low_balance_notification(
            user=user,
            required_amount=payment.amount,
            current_balance=wallet.balance,
            payment_purpose=f"Recurring {payment.bill_type} payment"
        )
        
        # Update next retry date (1 day later)
        await _update_recurring_payment_retry(
            session, payment, "Insufficient balance"
        )
        
        return {
            "id": payment.id,
            "status": "skipped",
            "reason": "insufficient_balance",
            "next_retry": payment.next_payment_date.isoformat() if payment.next_payment_date else None
        }
    
    # Execute payment
    try:
        payment_service = PaymentService(session)
        transaction = await payment_service.process_bill_payment(
            user_id=payment.user_id,
            bill_type=payment.bill_type,
            biller_code=payment.biller_code,
            amount=payment.amount,
            customer_identifier=payment.customer_identifier,
            metadata={
                "recurring_payment_id": payment.id,
                "is_recurring": True,
                "frequency": payment.frequency
            }
        )
        
        # Update recurring payment with success
        await _update_recurring_payment_success(session, payment)
        
        # Send success notification
        notification_service = NotificationService()
        await notification_service.send_recurring_payment_success_notification(
            user=user,
            amount=payment.amount,
            bill_type=payment.bill_type,
            transaction_reference=transaction.reference
        )
        
        # Dispatch webhook event
        await dispatch_event(
            EventTypes.RECURRING_PAYMENT_EXECUTED,
            {
                "recurring_payment_id": payment.id,
                "user_id": payment.user_id,
                "amount": float(payment.amount),
                "bill_type": payment.bill_type,
                "biller_code": payment.biller_code,
                "transaction_id": transaction.id,
                "transaction_reference": transaction.reference
            }
        )
        
        return {
            "id": payment.id,
            "status": "success",
            "transaction_id": transaction.id,
            "transaction_reference": transaction.reference,
            "next_payment_date": payment.next_payment_date.isoformat() if payment.next_payment_date else None
        }
        
    except Exception as e:
        logger.error(f"Failed to process recurring payment {payment.id}: {str(e)}")
        
        # Update recurring payment with failure
        await _update_recurring_payment_failure(
            session, payment, str(e)
        )
        
        # Send failure notification
        notification_service = NotificationService()
        await notification_service.send_recurring_payment_failure_notification(
            user=user,
            amount=payment.amount,
            bill_type=payment.bill_type,
            error_message=str(e)
        )
        
        # Dispatch webhook event
        await dispatch_event(
            EventTypes.RECURRING_PAYMENT_FAILED,
            {
                "recurring_payment_id": payment.id,
                "user_id": payment.user_id,
                "amount": float(payment.amount),
                "bill_type": payment.bill_type,
                "biller_code": payment.biller_code,
                "error": str(e)
            }
        )
        
        return {
            "id": payment.id,
            "status": "failed",
            "error": str(e),
            "next_retry": payment.next_payment_date.isoformat() if payment.next_payment_date else None
        }


async def _update_recurring_payment_success(
    session: AsyncSession,
    payment: RecurringPayment
) -> None:
    """Update recurring payment after successful execution.
    
    Args:
        session: Database session
        payment: Recurring payment to update
    """
    # Calculate next payment date based on frequency
    next_date = _calculate_next_payment_date(payment)
    
    # Update payment record
    payment.last_payment_date = datetime.utcnow()
    payment.next_payment_date = next_date
    payment.consecutive_failures = 0
    payment.last_error = None
    
    # Increment payment count
    payment.payment_count += 1
    
    await session.commit()


async def _update_recurring_payment_failure(
    session: AsyncSession,
    payment: RecurringPayment,
    error_message: str
) -> None:
    """Update recurring payment after failed execution.
    
    Args:
        session: Database session
        payment: Recurring payment to update
        error_message: Error message
    """
    # Increment failure count
    payment.consecutive_failures += 1
    payment.last_error = error_message
    
    # If too many consecutive failures, deactivate
    if payment.consecutive_failures >= 3:
        payment.status = RecurringPaymentStatus.ERROR
        payment.status_reason = f"Deactivated after {payment.consecutive_failures} consecutive failures"
    else:
        # Set next retry (1 day later)
        payment.next_payment_date = datetime.utcnow() + timedelta(days=1)
    
    await session.commit()


async def _update_recurring_payment_retry(
    session: AsyncSession,
    payment: RecurringPayment,
    reason: str
) -> None:
    """Update recurring payment for retry.
    
    Args:
        session: Database session
        payment: Recurring payment to update
        reason: Reason for retry
    """
    # Set next retry (1 day later)
    payment.next_payment_date = datetime.utcnow() + timedelta(days=1)
    payment.last_error = reason
    
    await session.commit()


async def _update_recurring_payment_status(
    session: AsyncSession,
    payment: RecurringPayment,
    status: RecurringPaymentStatus,
    reason: Optional[str] = None
) -> None:
    """Update recurring payment status.
    
    Args:
        session: Database session
        payment: Recurring payment to update
        status: New status
        reason: Status change reason
    """
    payment.status = status
    payment.status_reason = reason
    payment.updated_at = datetime.utcnow()
    
    await session.commit()


def _calculate_next_payment_date(payment: RecurringPayment) -> datetime:
    """Calculate next payment date based on frequency.
    
    Args:
        payment: Recurring payment
        
    Returns:
        datetime: Next payment date
    """
    now = datetime.utcnow()
    
    if payment.frequency == "daily":
        return now + timedelta(days=1)
    elif payment.frequency == "weekly":
        return now + timedelta(weeks=1)
    elif payment.frequency == "biweekly":
        return now + timedelta(weeks=2)
    elif payment.frequency == "monthly":
        # Add one month (approximately)
        if now.month == 12:
            return now.replace(year=now.year + 1, month=1)
        else:
            return now.replace(month=now.month + 1)
    elif payment.frequency == "quarterly":
        # Add three months
        month = now.month + 3
        year = now.year
        if month > 12:
            month -= 12
            year += 1
        return now.replace(year=year, month=month)
    else:
        # Default to monthly
        if now.month == 12:
            return now.replace(year=now.year + 1, month=1)
        else:
            return now.replace(month=now.month + 1)


@celery_app.task(name="app.tasks.recurring_payments.create_recurring_payment")
def create_recurring_payment(
    user_id: int,
    bill_type: str,
    biller_code: str,
    amount: float,
    customer_identifier: str,
    frequency: str = "monthly",
    start_date: Optional[str] = None
) -> Dict[str, Any]:
    """Create a new recurring payment.
    
    Args:
        user_id: User ID
        bill_type: Bill type
        biller_code: Biller code
        amount: Payment amount
        customer_identifier: Customer identifier
        frequency: Payment frequency
        start_date: Start date (optional)
        
    Returns:
        Dict[str, Any]: Created recurring payment details
    """
    logger.info(f"Creating recurring payment for user {user_id}")
    
    # Use sync-to-async pattern for Celery compatibility
    import asyncio
    return asyncio.run(_create_recurring_payment_async(
        user_id, bill_type, biller_code, amount, customer_identifier, frequency, start_date
    ))


async def _create_recurring_payment_async(
    user_id: int,
    bill_type: str,
    biller_code: str,
    amount: float,
    customer_identifier: str,
    frequency: str = "monthly",
    start_date: Optional[str] = None
) -> Dict[str, Any]:
    """Async implementation of recurring payment creation.
    
    Args:
        user_id: User ID
        bill_type: Bill type
        biller_code: Biller code
        amount: Payment amount
        customer_identifier: Customer identifier
        frequency: Payment frequency
        start_date: Start date (optional)
        
    Returns:
        Dict[str, Any]: Created recurring payment details
    """
    async with AsyncSessionLocal() as session:
        # Validate user exists
        user_query = select(User).where(User.id == user_id)
        user_result = await session.execute(user_query)
        user = user_result.scalar_one_or_none()
        
        if not user:
            raise ValueError(f"User with ID {user_id} not found")
        
        # Parse start date if provided
        if start_date:
            next_payment_date = datetime.fromisoformat(start_date)
        else:
            # Default to tomorrow
            next_payment_date = datetime.utcnow() + timedelta(days=1)
        
        # Create recurring payment
        recurring_payment = RecurringPayment(
            user_id=user_id,
            bill_type=bill_type,
            biller_code=biller_code,
            amount=amount,
            customer_identifier=customer_identifier,
            frequency=frequency,
            next_payment_date=next_payment_date,
            status=RecurringPaymentStatus.ACTIVE
        )
        
        session.add(recurring_payment)
        await session.commit()
        await session.refresh(recurring_payment)
        
        # Send notification
        notification_service = NotificationService()
        await notification_service.send_recurring_payment_created_notification(
            user=user,
            amount=amount,
            bill_type=bill_type,
            frequency=frequency,
            start_date=next_payment_date
        )
        
        # Dispatch webhook event
        await dispatch_event(
            EventTypes.RECURRING_PAYMENT_CREATED,
            {
                "recurring_payment_id": recurring_payment.id,
                "user_id": user_id,
                "amount": float(amount),
                "bill_type": bill_type,
                "biller_code": biller_code,
                "frequency": frequency,
                "next_payment_date": next_payment_date.isoformat()
            }
        )
        
        return {
            "id": recurring_payment.id,
            "user_id": recurring_payment.user_id,
            "bill_type": recurring_payment.bill_type,
            "biller_code": recurring_payment.biller_code,
            "amount": float(recurring_payment.amount),
            "customer_identifier": recurring_payment.customer_identifier,
            "frequency": recurring_payment.frequency,
            "next_payment_date": recurring_payment.next_payment_date.isoformat(),
            "status": recurring_payment.status.value
        }


@celery_app.task(name="app.tasks.recurring_payments.cancel_recurring_payment")
def cancel_recurring_payment(recurring_payment_id: int, reason: str) -> Dict[str, Any]:
    """Cancel a recurring payment.
    
    Args:
        recurring_payment_id: Recurring payment ID
        reason: Cancellation reason
        
    Returns:
        Dict[str, Any]: Cancellation result
    """
    logger.info(f"Cancelling recurring payment {recurring_payment_id}")
    
    # Use sync-to-async pattern for Celery compatibility
    import asyncio
    return asyncio.run(_cancel_recurring_payment_async(recurring_payment_id, reason))


async def _cancel_recurring_payment_async(recurring_payment_id: int, reason: str) -> Dict[str, Any]:
    """Async implementation of recurring payment cancellation.
    
    Args:
        recurring_payment_id: Recurring payment ID
        reason: Cancellation reason
        
    Returns:
        Dict[str, Any]: Cancellation result
    """
    async with AsyncSessionLocal() as session:
        # Find recurring payment
        query = select(RecurringPayment).where(RecurringPayment.id == recurring_payment_id)
        result = await session.execute(query)
        payment = result.scalar_one_or_none()
        
        if not payment:
            return {
                "success": False,
                "error": f"Recurring payment with ID {recurring_payment_id} not found"
            }
        
        # Update status
        payment.status = RecurringPaymentStatus.CANCELLED
        payment.status_reason = reason
        payment.updated_at = datetime.utcnow()
        
        await session.commit()
        
        # Get user for notification
        user_query = select(User).where(User.id == payment.user_id)
        user_result = await session.execute(user_query)
        user = user_result.scalar_one_or_none()
        
        if user:
            # Send notification
            notification_service = NotificationService()
            await notification_service.send_recurring_payment_cancelled_notification(
                user=user,
                amount=payment.amount,
                bill_type=payment.bill_type,
                reason=reason
            )
        
        return {
            "success": True,
            "id": payment.id,
            "status": payment.status.value,
            "reason": payment.status_reason
        }