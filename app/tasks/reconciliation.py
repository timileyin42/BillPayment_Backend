import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio

from app.core.database import AsyncSessionLocal
from app.database_model.transaction import Transaction, TransactionStatus
from app.database_model.wallet import Wallet, WalletTransaction, WalletTransactionType
from app.database_model.cashback import Cashback, CashbackStatus
from app.utils.idempotency import IdempotencyKey, IdempotencyManager
from app.services.payment_service import PaymentService
from app.services.wallet_service import WalletService
from app.services.notification import NotificationService
from app.utils.lock_manager import acquire_lock, LockPatterns
from app.tasks import celery_app


logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.reconciliation.reconcile_transactions")
def reconcile_transactions(hours_ago: int = 24) -> Dict[str, Any]:
    """Reconcile pending transactions.
    
    This task finds all transactions that have been in PENDING status for too long
    and attempts to reconcile them with the payment provider.
    
    Args:
        hours_ago: Hours to look back for pending transactions
        
    Returns:
        Dict[str, Any]: Reconciliation summary
    """
    logger.info(f"Starting transaction reconciliation for transactions from the last {hours_ago} hours")
    
    # Use sync-to-async pattern for Celery compatibility
    return asyncio.run(_reconcile_transactions_async(hours_ago))


async def _reconcile_transactions_async(hours_ago: int = 24) -> Dict[str, Any]:
    """Async implementation of transaction reconciliation.
    
    Args:
        hours_ago: Hours to look back for pending transactions
        
    Returns:
        Dict[str, Any]: Reconciliation summary
    """
    async with AsyncSessionLocal() as session:
        # Find pending transactions older than specified hours
        cutoff_time = datetime.utcnow() - timedelta(hours=hours_ago)
        
        query = select(Transaction).where(
            Transaction.status == TransactionStatus.PENDING,
            Transaction.created_at <= cutoff_time
        )
        
        result = await session.execute(query)
        pending_transactions = result.scalars().all()
        
        logger.info(f"Found {len(pending_transactions)} pending transactions to reconcile")
        
        summary = {
            "total": len(pending_transactions),
            "resolved": 0,
            "failed": 0,
            "still_pending": 0,
            "details": []
        }
        
        payment_service = PaymentService(session)
        
        for transaction in pending_transactions:
            try:
                # Use distributed lock to prevent concurrent reconciliation
                async with acquire_lock(LockPatterns.transaction_processing(transaction.id), timeout=60.0):
                    # Check transaction status with provider
                    provider_status = await payment_service.check_transaction_status(
                        transaction_id=transaction.id,
                        reference=transaction.reference,
                        bill_type=transaction.bill_type,
                        biller_code=transaction.biller_code
                    )
                    
                    # Process based on provider status
                    if provider_status["status"] == "success":
                        await _handle_successful_transaction(session, transaction, provider_status)
                        summary["resolved"] += 1
                        summary["details"].append({
                            "id": transaction.id,
                            "reference": transaction.reference,
                            "result": "success",
                            "provider_reference": provider_status.get("provider_reference")
                        })
                    elif provider_status["status"] == "failed":
                        await _handle_failed_transaction(session, transaction, provider_status)
                        summary["resolved"] += 1
                        summary["details"].append({
                            "id": transaction.id,
                            "reference": transaction.reference,
                            "result": "failed",
                            "reason": provider_status.get("reason")
                        })
                    else:
                        # Still pending with provider
                        summary["still_pending"] += 1
                        summary["details"].append({
                            "id": transaction.id,
                            "reference": transaction.reference,
                            "result": "still_pending"
                        })
            except Exception as e:
                logger.error(f"Error reconciling transaction {transaction.id}: {str(e)}")
                summary["failed"] += 1
                summary["details"].append({
                    "id": transaction.id,
                    "reference": transaction.reference,
                    "result": "error",
                    "error": str(e)
                })
        
        return summary


async def _handle_successful_transaction(
    session: AsyncSession,
    transaction: Transaction,
    provider_status: Dict[str, Any]
) -> None:
    """Handle a transaction that was confirmed successful by the provider.
    
    Args:
        session: Database session
        transaction: Transaction to update
        provider_status: Provider status information
    """
    logger.info(f"Confirming successful transaction {transaction.id}")
    
    # Update transaction status
    transaction.status = TransactionStatus.SUCCESS
    transaction.provider_reference = provider_status.get("provider_reference")
    transaction.updated_at = datetime.utcnow()
    transaction.metadata = {
        **(transaction.metadata or {}),
        "reconciliation": {
            "timestamp": datetime.utcnow().isoformat(),
            "provider_status": provider_status
        }
    }
    
    # Process cashback if applicable
    payment_service = PaymentService(session)
    await payment_service.process_cashback_for_transaction(transaction)
    
    # Send success notification
    notification_service = NotificationService()
    await notification_service.send_transaction_success_notification(
        transaction_id=transaction.id,
        user_id=transaction.user_id,
        amount=transaction.amount,
        bill_type=transaction.bill_type
    )
    
    await session.commit()


async def _handle_failed_transaction(
    session: AsyncSession,
    transaction: Transaction,
    provider_status: Dict[str, Any]
) -> None:
    """Handle a transaction that was confirmed failed by the provider.
    
    Args:
        session: Database session
        transaction: Transaction to update
        provider_status: Provider status information
    """
    logger.info(f"Marking transaction {transaction.id} as failed")
    
    # Update transaction status
    transaction.status = TransactionStatus.FAILED
    transaction.failure_reason = provider_status.get("reason")
    transaction.updated_at = datetime.utcnow()
    transaction.metadata = {
        **(transaction.metadata or {}),
        "reconciliation": {
            "timestamp": datetime.utcnow().isoformat(),
            "provider_status": provider_status
        }
    }
    
    # Refund wallet if amount was deducted
    wallet_service = WalletService(session)
    await wallet_service.refund_failed_transaction(
        user_id=transaction.user_id,
        amount=transaction.amount,
        transaction_reference=transaction.reference,
        description=f"Refund for failed {transaction.bill_type} payment"
    )
    
    # Send failure notification
    notification_service = NotificationService()
    await notification_service.send_transaction_failure_notification(
        transaction_id=transaction.id,
        user_id=transaction.user_id,
        amount=transaction.amount,
        bill_type=transaction.bill_type,
        reason=provider_status.get("reason")
    )
    
    await session.commit()


@celery_app.task(name="app.tasks.reconciliation.reconcile_wallet_balances")
def reconcile_wallet_balances() -> Dict[str, Any]:
    """Reconcile wallet balances with transaction history.
    
    This task verifies that wallet balances match the sum of their transactions
    and corrects any discrepancies.
    
    Returns:
        Dict[str, Any]: Reconciliation summary
    """
    logger.info("Starting wallet balance reconciliation")
    
    # Use sync-to-async pattern for Celery compatibility
    return asyncio.run(_reconcile_wallet_balances_async())


async def _reconcile_wallet_balances_async() -> Dict[str, Any]:
    """Async implementation of wallet balance reconciliation.
    
    Returns:
        Dict[str, Any]: Reconciliation summary
    """
    async with AsyncSessionLocal() as session:
        # Get all wallets
        wallet_query = select(Wallet)
        wallet_result = await session.execute(wallet_query)
        wallets = wallet_result.scalars().all()
        
        summary = {
            "total_wallets": len(wallets),
            "discrepancies_found": 0,
            "corrections_made": 0,
            "details": []
        }
        
        for wallet in wallets:
            try:
                # Use distributed lock to prevent concurrent modifications
                async with acquire_lock(LockPatterns.user_wallet(wallet.user_id), timeout=30.0):
                    # Calculate expected balance from transactions
                    expected_balance, discrepancy = await _calculate_expected_wallet_balance(session, wallet)
                    
                    if abs(discrepancy) > 0.01:  # Allow for small floating-point differences
                        summary["discrepancies_found"] += 1
                        
                        # Correct the balance
                        await _correct_wallet_balance(
                            session, wallet, expected_balance, discrepancy
                        )
                        
                        summary["corrections_made"] += 1
                        summary["details"].append({
                            "wallet_id": wallet.id,
                            "user_id": wallet.user_id,
                            "previous_balance": float(wallet.balance),
                            "corrected_balance": float(expected_balance),
                            "discrepancy": float(discrepancy)
                        })
            except Exception as e:
                logger.error(f"Error reconciling wallet {wallet.id}: {str(e)}")
                summary["details"].append({
                    "wallet_id": wallet.id,
                    "user_id": wallet.user_id,
                    "error": str(e)
                })
        
        return summary


async def _calculate_expected_wallet_balance(
    session: AsyncSession, wallet: Wallet
) -> Tuple[float, float]:
    """Calculate expected wallet balance from transaction history.
    
    Args:
        session: Database session
        wallet: Wallet to check
        
    Returns:
        Tuple[float, float]: (expected_balance, discrepancy)
    """
    # Sum all credits and debits
    query = select(
        func.sum(WalletTransaction.amount).label("total")
    ).where(
        WalletTransaction.wallet_id == wallet.id,
        WalletTransaction.type == WalletTransactionType.CREDIT
    )
    
    result = await session.execute(query)
    total_credits = result.scalar() or 0
    
    query = select(
        func.sum(WalletTransaction.amount).label("total")
    ).where(
        WalletTransaction.wallet_id == wallet.id,
        WalletTransaction.type == WalletTransactionType.DEBIT
    )
    
    result = await session.execute(query)
    total_debits = result.scalar() or 0
    
    expected_balance = total_credits - total_debits
    discrepancy = wallet.balance - expected_balance
    
    return expected_balance, discrepancy


async def _correct_wallet_balance(
    session: AsyncSession,
    wallet: Wallet,
    expected_balance: float,
    discrepancy: float
) -> None:
    """Correct wallet balance and log the adjustment.
    
    Args:
        session: Database session
        wallet: Wallet to correct
        expected_balance: Expected balance
        discrepancy: Amount of discrepancy
    """
    logger.warning(
        f"Correcting wallet balance for user {wallet.user_id}: "
        f"current={wallet.balance}, expected={expected_balance}, discrepancy={discrepancy}"
    )
    
    # Create adjustment transaction
    adjustment = WalletTransaction(
        wallet_id=wallet.id,
        amount=abs(discrepancy),
        type=WalletTransactionType.CREDIT if discrepancy < 0 else WalletTransactionType.DEBIT,
        description="Balance reconciliation adjustment",
        reference=f"RECON-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
        metadata={
            "reconciliation": True,
            "previous_balance": float(wallet.balance),
            "expected_balance": float(expected_balance),
            "discrepancy": float(discrepancy)
        }
    )
    
    session.add(adjustment)
    
    # Update wallet balance
    wallet.balance = expected_balance
    wallet.updated_at = datetime.utcnow()
    
    await session.commit()
    
    # Send notification to user
    notification_service = NotificationService()
    await notification_service.send_wallet_reconciliation_notification(
        user_id=wallet.user_id,
        previous_balance=wallet.balance,
        new_balance=expected_balance,
        adjustment=abs(discrepancy)
    )


@celery_app.task(name="app.tasks.reconciliation.cleanup_expired_idempotency_keys")
def cleanup_expired_idempotency_keys() -> Dict[str, Any]:
    """Clean up expired idempotency keys.
    
    Returns:
        Dict[str, Any]: Cleanup summary
    """
    logger.info("Starting cleanup of expired idempotency keys")
    
    # Use sync-to-async pattern for Celery compatibility
    return asyncio.run(_cleanup_expired_idempotency_keys_async())


async def _cleanup_expired_idempotency_keys_async() -> Dict[str, Any]:
    """Async implementation of idempotency key cleanup.
    
    Returns:
        Dict[str, Any]: Cleanup summary
    """
    async with AsyncSessionLocal() as session:
        manager = IdempotencyManager(session)
        deleted_count = await manager.cleanup_expired_keys()
        
        return {
            "deleted_count": deleted_count,
            "timestamp": datetime.utcnow().isoformat()
        }


@celery_app.task(name="app.tasks.reconciliation.process_pending_cashbacks")
def process_pending_cashbacks() -> Dict[str, Any]:
    """Process pending cashbacks that are ready to be credited.
    
    Returns:
        Dict[str, Any]: Processing summary
    """
    logger.info("Starting processing of pending cashbacks")
    
    # Use sync-to-async pattern for Celery compatibility
    return asyncio.run(_process_pending_cashbacks_async())


async def _process_pending_cashbacks_async() -> Dict[str, Any]:
    """Async implementation of pending cashback processing.
    
    Returns:
        Dict[str, Any]: Processing summary
    """
    async with AsyncSessionLocal() as session:
        # Find pending cashbacks that are ready to be credited
        query = select(Cashback).where(
            Cashback.status == CashbackStatus.PENDING,
            Cashback.eligible_date <= datetime.utcnow()
        )
        
        result = await session.execute(query)
        pending_cashbacks = result.scalars().all()
        
        logger.info(f"Found {len(pending_cashbacks)} pending cashbacks to process")
        
        summary = {
            "total": len(pending_cashbacks),
            "credited": 0,
            "failed": 0,
            "details": []
        }
        
        wallet_service = WalletService(session)
        
        for cashback in pending_cashbacks:
            try:
                # Use distributed lock to prevent concurrent processing
                async with acquire_lock(LockPatterns.cashback_calculation(cashback.user_id), timeout=30.0):
                    # Credit cashback to wallet
                    await wallet_service.credit_cashback_to_wallet(
                        user_id=cashback.user_id,
                        amount=cashback.amount,
                        cashback_id=cashback.id,
                        description=f"Cashback for {cashback.source_type}: {cashback.description}"
                    )
                    
                    # Update cashback status
                    cashback.status = CashbackStatus.CREDITED
                    cashback.credited_date = datetime.utcnow()
                    
                    await session.commit()
                    
                    # Send notification
                    notification_service = NotificationService()
                    await notification_service.send_cashback_credited_notification(
                        user_id=cashback.user_id,
                        amount=cashback.amount,
                        description=cashback.description
                    )
                    
                    summary["credited"] += 1
                    summary["details"].append({
                        "id": cashback.id,
                        "user_id": cashback.user_id,
                        "amount": float(cashback.amount),
                        "result": "credited"
                    })
            except Exception as e:
                logger.error(f"Error processing cashback {cashback.id}: {str(e)}")
                summary["failed"] += 1
                summary["details"].append({
                    "id": cashback.id,
                    "user_id": cashback.user_id,
                    "amount": float(cashback.amount),
                    "result": "failed",
                    "error": str(e)
                })
        
        return summary