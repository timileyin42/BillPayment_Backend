import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio

from app.core.database import AsyncSessionLocal
from app.database_model.cashback import Cashback, ReferralReward
from app.database_model.user import User
from app.database_model.wallet import Wallet
from app.services.notification import NotificationService
from app.utils.webhooks import dispatch_event, EventTypes
from app.tasks import celery_app


logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.cashback_tasks.expire_cashback")
def expire_cashback() -> Dict[str, Any]:
    """Mark expired cashback as expired and update wallet balances.
    
    This task finds all cashback records that have passed their expiry date
    and marks them as expired, removing them from user wallet balances.
    
    Returns:
        Dict[str, Any]: Summary of expired cashback processing
    """
    logger.info("Starting cashback expiry processing")
    
    # Use sync-to-async pattern for Celery compatibility
    return asyncio.run(_expire_cashback_async())


async def _expire_cashback_async() -> Dict[str, Any]:
    """Async implementation of cashback expiry processing.
    
    Returns:
        Dict[str, Any]: Summary of expired cashback processing
    """
    async with AsyncSessionLocal() as session:
        # Find all credited cashback that has expired
        expired_cashbacks = await _get_expired_cashbacks(session)
        
        logger.info(f"Found {len(expired_cashbacks)} expired cashback records")
        
        results = {
            "total": len(expired_cashbacks),
            "processed": 0,
            "failed": 0,
            "total_amount_expired": 0.0,
            "details": []
        }
        
        for cashback in expired_cashbacks:
            try:
                result = await _process_expired_cashback(session, cashback)
                results["details"].append(result)
                
                if result["status"] == "success":
                    results["processed"] += 1
                    results["total_amount_expired"] += result["amount"]
                else:
                    results["failed"] += 1
                    
            except Exception as e:
                logger.error(f"Error processing expired cashback {cashback.id}: {str(e)}")
                results["failed"] += 1
                results["details"].append({
                    "id": cashback.id,
                    "status": "failed",
                    "error": str(e)
                })
        
        await session.commit()
        return results


async def _get_expired_cashbacks(session: AsyncSession) -> List[Cashback]:
    """Get all expired cashback records that are still credited.
    
    Args:
        session: Database session
        
    Returns:
        List[Cashback]: List of expired cashback records
    """
    now = datetime.utcnow()
    
    # Find all credited cashback that has expired
    query = select(Cashback).where(
        Cashback.status == "credited",
        Cashback.expires_at <= now,
        Cashback.expires_at.isnot(None)
    )
    
    result = await session.execute(query)
    return result.scalars().all()


async def _process_expired_cashback(
    session: AsyncSession,
    cashback: Cashback
) -> Dict[str, Any]:
    """Process a single expired cashback record.
    
    Args:
        session: Database session
        cashback: Expired cashback record to process
        
    Returns:
        Dict[str, Any]: Result of cashback expiry processing
    """
    logger.info(f"Processing expired cashback {cashback.id} for user {cashback.user_id}")
    
    # Get user wallet
    wallet_query = select(Wallet).where(Wallet.user_id == cashback.user_id)
    wallet_result = await session.execute(wallet_query)
    wallet = wallet_result.scalar_one_or_none()
    
    if not wallet:
        logger.error(f"Wallet not found for user {cashback.user_id}")
        return {
            "id": cashback.id,
            "status": "failed",
            "error": "Wallet not found"
        }
    
    # Update cashback status to expired
    cashback.status = "expired"
    cashback.updated_at = datetime.utcnow()
    
    # Deduct expired cashback from wallet balance
    if wallet.cashback_balance >= cashback.cashback_amount:
        wallet.cashback_balance -= cashback.cashback_amount
        wallet.updated_at = datetime.utcnow()
    else:
        logger.warning(
            f"Insufficient cashback balance for user {cashback.user_id}. "
            f"Required: {cashback.cashback_amount}, Available: {wallet.cashback_balance}"
        )
        # Set cashback balance to 0 if insufficient
        wallet.cashback_balance = 0.0
        wallet.updated_at = datetime.utcnow()
    
    # Dispatch webhook event
    await dispatch_event(
        EventTypes.CASHBACK_EXPIRED,
        {
            "cashback_id": cashback.id,
            "user_id": cashback.user_id,
            "amount": float(cashback.cashback_amount),
            "expired_at": cashback.expires_at.isoformat() if cashback.expires_at else None,
            "transaction_id": cashback.transaction_id
        }
    )
    
    return {
        "id": cashback.id,
        "status": "success",
        "amount": float(cashback.cashback_amount),
        "user_id": cashback.user_id
    }


@celery_app.task(name="app.tasks.cashback_tasks.send_expiry_notifications")
def send_expiry_notifications() -> Dict[str, Any]:
    """Send notifications for cashback that will expire soon.
    
    This task finds cashback records that will expire within the next 7 days
    and sends reminder notifications to users.
    
    Returns:
        Dict[str, Any]: Summary of expiry notifications sent
    """
    logger.info("Starting cashback expiry notifications")
    
    # Use sync-to-async pattern for Celery compatibility
    return asyncio.run(_send_expiry_notifications_async())


async def _send_expiry_notifications_async() -> Dict[str, Any]:
    """Async implementation of cashback expiry notifications.
    
    Returns:
        Dict[str, Any]: Summary of expiry notifications sent
    """
    async with AsyncSessionLocal() as session:
        # Find cashback expiring in the next 7 days
        expiring_cashbacks = await _get_expiring_cashbacks(session)
        
        logger.info(f"Found {len(expiring_cashbacks)} cashback records expiring soon")
        
        results = {
            "total": len(expiring_cashbacks),
            "notifications_sent": 0,
            "failed": 0,
            "details": []
        }
        
        # Group by user to send consolidated notifications
        user_cashbacks: Dict[int, List[Cashback]] = {}
        for cashback in expiring_cashbacks:
            if cashback.user_id not in user_cashbacks:
                user_cashbacks[cashback.user_id] = []
            user_cashbacks[cashback.user_id].append(cashback)
        
        for user_id, cashbacks in user_cashbacks.items():
            try:
                result = await _send_user_expiry_notification(session, user_id, cashbacks)
                results["details"].append(result)
                
                if result["status"] == "success":
                    results["notifications_sent"] += 1
                else:
                    results["failed"] += 1
                    
            except Exception as e:
                logger.error(f"Error sending expiry notification to user {user_id}: {str(e)}")
                results["failed"] += 1
                results["details"].append({
                    "user_id": user_id,
                    "status": "failed",
                    "error": str(e)
                })
        
        return results


async def _get_expiring_cashbacks(session: AsyncSession) -> List[Cashback]:
    """Get cashback records that will expire within the next 7 days.
    
    Args:
        session: Database session
        
    Returns:
        List[Cashback]: List of expiring cashback records
    """
    now = datetime.utcnow()
    expiry_threshold = now + timedelta(days=7)
    
    # Find credited cashback expiring within 7 days
    query = select(Cashback).where(
        Cashback.status == "credited",
        Cashback.expires_at > now,
        Cashback.expires_at <= expiry_threshold,
        Cashback.expires_at.isnot(None)
    )
    
    result = await session.execute(query)
    return result.scalars().all()


async def _send_user_expiry_notification(
    session: AsyncSession,
    user_id: int,
    cashbacks: List[Cashback]
) -> Dict[str, Any]:
    """Send expiry notification to a specific user.
    
    Args:
        session: Database session
        user_id: User ID to send notification to
        cashbacks: List of expiring cashback records for the user
        
    Returns:
        Dict[str, Any]: Result of notification sending
    """
    # Get user details
    user_query = select(User).where(User.id == user_id)
    user_result = await session.execute(user_query)
    user = user_result.scalar_one_or_none()
    
    if not user:
        logger.error(f"User {user_id} not found")
        return {
            "user_id": user_id,
            "status": "failed",
            "error": "User not found"
        }
    
    # Calculate total expiring amount
    total_amount = sum(cashback.cashback_amount for cashback in cashbacks)
    
    # Find the earliest expiry date
    earliest_expiry = min(cashback.expires_at for cashback in cashbacks if cashback.expires_at)
    
    # Send notification
    notification_service = NotificationService()
    await notification_service.send_cashback_expiry_notification(
        user=user,
        total_amount=total_amount,
        expiry_date=earliest_expiry,
        cashback_count=len(cashbacks)
    )
    
    return {
        "user_id": user_id,
        "status": "success",
        "total_amount": float(total_amount),
        "cashback_count": len(cashbacks),
        "earliest_expiry": earliest_expiry.isoformat() if earliest_expiry else None
    }


@celery_app.task(name="app.tasks.cashback_tasks.expire_referral_rewards")
def expire_referral_rewards() -> Dict[str, Any]:
    """Mark expired referral rewards as expired.
    
    This task finds referral rewards that have been pending for too long
    (e.g., 90 days) and marks them as expired.
    
    Returns:
        Dict[str, Any]: Summary of expired referral rewards processing
    """
    logger.info("Starting referral rewards expiry processing")
    
    # Use sync-to-async pattern for Celery compatibility
    return asyncio.run(_expire_referral_rewards_async())


async def _expire_referral_rewards_async() -> Dict[str, Any]:
    """Async implementation of referral rewards expiry processing.
    
    Returns:
        Dict[str, Any]: Summary of expired referral rewards processing
    """
    async with AsyncSessionLocal() as session:
        # Find referral rewards that are pending for more than 90 days
        expiry_threshold = datetime.utcnow() - timedelta(days=90)
        
        query = select(ReferralReward).where(
            ReferralReward.status == "pending",
            ReferralReward.created_at <= expiry_threshold
        )
        
        result = await session.execute(query)
        expired_rewards = result.scalars().all()
        
        logger.info(f"Found {len(expired_rewards)} expired referral rewards")
        
        results = {
            "total": len(expired_rewards),
            "processed": 0,
            "failed": 0,
            "total_amount_expired": 0.0
        }
        
        for reward in expired_rewards:
            try:
                reward.status = "expired"
                reward.updated_at = datetime.utcnow()
                results["processed"] += 1
                results["total_amount_expired"] += reward.reward_amount
                
            except Exception as e:
                logger.error(f"Error expiring referral reward {reward.id}: {str(e)}")
                results["failed"] += 1
        
        await session.commit()
        return results