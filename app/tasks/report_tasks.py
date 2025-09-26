import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio
import json
from decimal import Decimal

from app.core.database import AsyncSessionLocal
from app.database_model.transaction import Transaction
from app.database_model.cashback import Cashback
from app.database_model.user import User
from app.database_model.wallet import Wallet, WalletTransaction
from app.database_model.biller import Biller
from app.services.notification import NotificationService
from app.utils.webhooks import dispatch_event, EventTypes
from app.tasks import celery_app


logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.report_tasks.generate_daily_transaction_report")
def generate_daily_transaction_report(report_date: Optional[str] = None) -> Dict[str, Any]:
    """Generate daily transaction report for the specified date.
    
    This task generates a comprehensive daily report including:
    - Transaction volume and value
    - Success/failure rates
    - Cashback distribution
    - Revenue metrics
    
    Args:
        report_date: Date in YYYY-MM-DD format. Defaults to yesterday.
        
    Returns:
        Dict[str, Any]: Daily transaction report data
    """
    if report_date:
        target_date = datetime.strptime(report_date, "%Y-%m-%d").date()
    else:
        # Default to yesterday
        target_date = (datetime.utcnow() - timedelta(days=1)).date()
    
    logger.info(f"Generating daily transaction report for {target_date}")
    
    # Use sync-to-async pattern for Celery compatibility
    return asyncio.run(_generate_daily_transaction_report_async(target_date))


async def _generate_daily_transaction_report_async(report_date: datetime.date) -> Dict[str, Any]:
    """Async implementation of daily transaction report generation.
    
    Args:
        report_date: Date to generate report for
        
    Returns:
        Dict[str, Any]: Daily transaction report data
    """
    async with AsyncSessionLocal() as session:
        # Define date range for the report
        start_datetime = datetime.combine(report_date, datetime.min.time())
        end_datetime = datetime.combine(report_date, datetime.max.time())
        
        # Generate comprehensive report
        report = {
            "report_date": report_date.isoformat(),
            "generated_at": datetime.utcnow().isoformat(),
            "transaction_metrics": await _get_transaction_metrics(session, start_datetime, end_datetime),
            "cashback_metrics": await _get_cashback_metrics(session, start_datetime, end_datetime),
            "revenue_metrics": await _get_revenue_metrics(session, start_datetime, end_datetime),
            "biller_breakdown": await _get_biller_breakdown(session, start_datetime, end_datetime),
            "user_activity": await _get_user_activity_metrics(session, start_datetime, end_datetime)
        }
        
        # Store report (you might want to save this to a reports table)
        logger.info(f"Daily report generated for {report_date}: {json.dumps(report, indent=2)}")
        
        # Dispatch webhook event for report generation
        await dispatch_event(
            EventTypes.DAILY_REPORT_GENERATED,
            {
                "report_date": report_date.isoformat(),
                "total_transactions": report["transaction_metrics"]["total_count"],
                "total_volume": report["transaction_metrics"]["total_volume"],
                "success_rate": report["transaction_metrics"]["success_rate"]
            }
        )
        
        return report


async def _get_transaction_metrics(
    session: AsyncSession,
    start_datetime: datetime,
    end_datetime: datetime
) -> Dict[str, Any]:
    """Get transaction metrics for the specified date range.
    
    Args:
        session: Database session
        start_datetime: Start of date range
        end_datetime: End of date range
        
    Returns:
        Dict[str, Any]: Transaction metrics
    """
    # Total transactions
    total_query = select(func.count(Transaction.id)).where(
        and_(
            Transaction.created_at >= start_datetime,
            Transaction.created_at <= end_datetime
        )
    )
    total_result = await session.execute(total_query)
    total_count = total_result.scalar() or 0
    
    # Successful transactions
    success_query = select(func.count(Transaction.id)).where(
        and_(
            Transaction.created_at >= start_datetime,
            Transaction.created_at <= end_datetime,
            Transaction.status == "completed"
        )
    )
    success_result = await session.execute(success_query)
    success_count = success_result.scalar() or 0
    
    # Failed transactions
    failed_query = select(func.count(Transaction.id)).where(
        and_(
            Transaction.created_at >= start_datetime,
            Transaction.created_at <= end_datetime,
            Transaction.status == "failed"
        )
    )
    failed_result = await session.execute(failed_query)
    failed_count = failed_result.scalar() or 0
    
    # Transaction volume (total amount)
    volume_query = select(func.sum(Transaction.total_amount)).where(
        and_(
            Transaction.created_at >= start_datetime,
            Transaction.created_at <= end_datetime,
            Transaction.status == "completed"
        )
    )
    volume_result = await session.execute(volume_query)
    total_volume = float(volume_result.scalar() or 0)
    
    # Average transaction amount
    avg_amount = total_volume / success_count if success_count > 0 else 0
    
    return {
        "total_count": total_count,
        "success_count": success_count,
        "failed_count": failed_count,
        "pending_count": total_count - success_count - failed_count,
        "success_rate": (success_count / total_count * 100) if total_count > 0 else 0,
        "failure_rate": (failed_count / total_count * 100) if total_count > 0 else 0,
        "total_volume": total_volume,
        "average_amount": avg_amount
    }


async def _get_cashback_metrics(
    session: AsyncSession,
    start_datetime: datetime,
    end_datetime: datetime
) -> Dict[str, Any]:
    """Get cashback metrics for the specified date range.
    
    Args:
        session: Database session
        start_datetime: Start of date range
        end_datetime: End of date range
        
    Returns:
        Dict[str, Any]: Cashback metrics
    """
    # Total cashback distributed
    cashback_query = select(
        func.count(Cashback.id),
        func.sum(Cashback.cashback_amount)
    ).where(
        and_(
            Cashback.created_at >= start_datetime,
            Cashback.created_at <= end_datetime,
            Cashback.status == "credited"
        )
    )
    cashback_result = await session.execute(cashback_query)
    cashback_count, cashback_amount = cashback_result.first() or (0, 0)
    
    # Cashback by type
    cashback_by_type_query = select(
        Cashback.cashback_type,
        func.count(Cashback.id),
        func.sum(Cashback.cashback_amount)
    ).where(
        and_(
            Cashback.created_at >= start_datetime,
            Cashback.created_at <= end_datetime,
            Cashback.status == "credited"
        )
    ).group_by(Cashback.cashback_type)
    
    cashback_by_type_result = await session.execute(cashback_by_type_query)
    cashback_by_type = {
        row[0]: {"count": row[1], "amount": float(row[2] or 0)}
        for row in cashback_by_type_result
    }
    
    return {
        "total_cashback_count": cashback_count or 0,
        "total_cashback_amount": float(cashback_amount or 0),
        "cashback_by_type": cashback_by_type
    }


async def _get_revenue_metrics(
    session: AsyncSession,
    start_datetime: datetime,
    end_datetime: datetime
) -> Dict[str, Any]:
    """Get revenue metrics for the specified date range.
    
    Args:
        session: Database session
        start_datetime: Start of date range
        end_datetime: End of date range
        
    Returns:
        Dict[str, Any]: Revenue metrics
    """
    # Total fees collected
    fees_query = select(func.sum(Transaction.transaction_fee)).where(
        and_(
            Transaction.created_at >= start_datetime,
            Transaction.created_at <= end_datetime,
            Transaction.status == "completed"
        )
    )
    fees_result = await session.execute(fees_query)
    total_fees = float(fees_result.scalar() or 0)
    
    # Cashback distributed (cost)
    cashback_cost_query = select(func.sum(Cashback.cashback_amount)).where(
        and_(
            Cashback.created_at >= start_datetime,
            Cashback.created_at <= end_datetime,
            Cashback.status == "credited"
        )
    )
    cashback_cost_result = await session.execute(cashback_cost_query)
    cashback_cost = float(cashback_cost_result.scalar() or 0)
    
    # Net revenue (fees - cashback)
    net_revenue = total_fees - cashback_cost
    
    return {
        "total_fees_collected": total_fees,
        "total_cashback_distributed": cashback_cost,
        "net_revenue": net_revenue,
        "cashback_ratio": (cashback_cost / total_fees * 100) if total_fees > 0 else 0
    }


async def _get_biller_breakdown(
    session: AsyncSession,
    start_datetime: datetime,
    end_datetime: datetime
) -> Dict[str, Any]:
    """Get transaction breakdown by biller.
    
    Args:
        session: Database session
        start_datetime: Start of date range
        end_datetime: End of date range
        
    Returns:
        Dict[str, Any]: Biller breakdown
    """
    biller_query = select(
        Biller.name,
        Transaction.bill_type,
        func.count(Transaction.id),
        func.sum(Transaction.total_amount)
    ).join(
        Biller, Transaction.biller_id == Biller.id
    ).where(
        and_(
            Transaction.created_at >= start_datetime,
            Transaction.created_at <= end_datetime,
            Transaction.status == "completed"
        )
    ).group_by(Biller.name, Transaction.bill_type)
    
    biller_result = await session.execute(biller_query)
    
    breakdown = {}
    for row in biller_result:
        biller_name, bill_type, count, amount = row
        if biller_name not in breakdown:
            breakdown[biller_name] = {}
        breakdown[biller_name][bill_type] = {
            "transaction_count": count,
            "total_amount": float(amount or 0)
        }
    
    return breakdown


async def _get_user_activity_metrics(
    session: AsyncSession,
    start_datetime: datetime,
    end_datetime: datetime
) -> Dict[str, Any]:
    """Get user activity metrics for the specified date range.
    
    Args:
        session: Database session
        start_datetime: Start of date range
        end_datetime: End of date range
        
    Returns:
        Dict[str, Any]: User activity metrics
    """
    # Active users (users who made transactions)
    active_users_query = select(func.count(func.distinct(Transaction.user_id))).where(
        and_(
            Transaction.created_at >= start_datetime,
            Transaction.created_at <= end_datetime
        )
    )
    active_users_result = await session.execute(active_users_query)
    active_users = active_users_result.scalar() or 0
    
    # New users (users who registered on this date)
    new_users_query = select(func.count(User.id)).where(
        and_(
            User.created_at >= start_datetime,
            User.created_at <= end_datetime
        )
    )
    new_users_result = await session.execute(new_users_query)
    new_users = new_users_result.scalar() or 0
    
    return {
        "active_users": active_users,
        "new_users": new_users
    }


@celery_app.task(name="app.tasks.report_tasks.generate_monthly_analytics")
def generate_monthly_analytics(report_month: Optional[str] = None) -> Dict[str, Any]:
    """Generate monthly analytics report.
    
    This task generates comprehensive monthly analytics including:
    - Monthly trends and comparisons
    - User growth metrics
    - Revenue analysis
    - Top performing billers
    
    Args:
        report_month: Month in YYYY-MM format. Defaults to last month.
        
    Returns:
        Dict[str, Any]: Monthly analytics report data
    """
    if report_month:
        year, month = map(int, report_month.split('-'))
        target_date = datetime(year, month, 1).date()
    else:
        # Default to last month
        today = datetime.utcnow().date()
        if today.month == 1:
            target_date = datetime(today.year - 1, 12, 1).date()
        else:
            target_date = datetime(today.year, today.month - 1, 1).date()
    
    logger.info(f"Generating monthly analytics for {target_date.strftime('%Y-%m')}")
    
    # Use sync-to-async pattern for Celery compatibility
    return asyncio.run(_generate_monthly_analytics_async(target_date))


async def _generate_monthly_analytics_async(report_month: datetime.date) -> Dict[str, Any]:
    """Async implementation of monthly analytics generation.
    
    Args:
        report_month: First day of the month to generate analytics for
        
    Returns:
        Dict[str, Any]: Monthly analytics report data
    """
    async with AsyncSessionLocal() as session:
        # Calculate month boundaries
        start_date = report_month
        if start_date.month == 12:
            end_date = datetime(start_date.year + 1, 1, 1).date() - timedelta(days=1)
        else:
            end_date = datetime(start_date.year, start_date.month + 1, 1).date() - timedelta(days=1)
        
        start_datetime = datetime.combine(start_date, datetime.min.time())
        end_datetime = datetime.combine(end_date, datetime.max.time())
        
        # Generate comprehensive monthly report
        report = {
            "report_month": start_date.strftime("%Y-%m"),
            "generated_at": datetime.utcnow().isoformat(),
            "period": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat()
            },
            "transaction_summary": await _get_monthly_transaction_summary(session, start_datetime, end_datetime),
            "user_growth": await _get_monthly_user_growth(session, start_datetime, end_datetime),
            "revenue_analysis": await _get_monthly_revenue_analysis(session, start_datetime, end_datetime),
            "top_billers": await _get_top_billers_monthly(session, start_datetime, end_datetime),
            "cashback_analysis": await _get_monthly_cashback_analysis(session, start_datetime, end_datetime)
        }
        
        # Store report (you might want to save this to a monthly_reports table)
        logger.info(f"Monthly analytics generated for {start_date.strftime('%Y-%m')}")
        
        # Dispatch webhook event for monthly report generation
        await dispatch_event(
            EventTypes.MONTHLY_REPORT_GENERATED,
            {
                "report_month": start_date.strftime("%Y-%m"),
                "total_transactions": report["transaction_summary"]["total_transactions"],
                "total_revenue": report["revenue_analysis"]["total_revenue"],
                "new_users": report["user_growth"]["new_users"]
            }
        )
        
        return report


async def _get_monthly_transaction_summary(
    session: AsyncSession,
    start_datetime: datetime,
    end_datetime: datetime
) -> Dict[str, Any]:
    """Get monthly transaction summary."""
    # Similar to daily metrics but for the entire month
    return await _get_transaction_metrics(session, start_datetime, end_datetime)


async def _get_monthly_user_growth(
    session: AsyncSession,
    start_datetime: datetime,
    end_datetime: datetime
) -> Dict[str, Any]:
    """Get monthly user growth metrics."""
    # New users this month
    new_users_query = select(func.count(User.id)).where(
        and_(
            User.created_at >= start_datetime,
            User.created_at <= end_datetime
        )
    )
    new_users_result = await session.execute(new_users_query)
    new_users = new_users_result.scalar() or 0
    
    # Total users at end of month
    total_users_query = select(func.count(User.id)).where(
        User.created_at <= end_datetime
    )
    total_users_result = await session.execute(total_users_query)
    total_users = total_users_result.scalar() or 0
    
    return {
        "new_users": new_users,
        "total_users": total_users,
        "growth_rate": (new_users / (total_users - new_users) * 100) if (total_users - new_users) > 0 else 0
    }


async def _get_monthly_revenue_analysis(
    session: AsyncSession,
    start_datetime: datetime,
    end_datetime: datetime
) -> Dict[str, Any]:
    """Get monthly revenue analysis."""
    return await _get_revenue_metrics(session, start_datetime, end_datetime)


async def _get_top_billers_monthly(
    session: AsyncSession,
    start_datetime: datetime,
    end_datetime: datetime
) -> List[Dict[str, Any]]:
    """Get top performing billers for the month."""
    top_billers_query = select(
        Biller.name,
        func.count(Transaction.id).label('transaction_count'),
        func.sum(Transaction.total_amount).label('total_volume')
    ).join(
        Biller, Transaction.biller_id == Biller.id
    ).where(
        and_(
            Transaction.created_at >= start_datetime,
            Transaction.created_at <= end_datetime,
            Transaction.status == "completed"
        )
    ).group_by(Biller.name).order_by(
        func.sum(Transaction.total_amount).desc()
    ).limit(10)
    
    result = await session.execute(top_billers_query)
    
    return [
        {
            "biller_name": row[0],
            "transaction_count": row[1],
            "total_volume": float(row[2] or 0)
        }
        for row in result
    ]


async def _get_monthly_cashback_analysis(
    session: AsyncSession,
    start_datetime: datetime,
    end_datetime: datetime
) -> Dict[str, Any]:
    """Get monthly cashback analysis."""
    return await _get_cashback_metrics(session, start_datetime, end_datetime)