from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from ..core.database import get_database_session
from ..services.archive_service import ArchiveService
from ..middleware.auth import get_current_user, get_current_admin_user
from ..database_model.user import User

router = APIRouter(prefix="/archive", tags=["Archive"])


class ArchivedTransactionResponse(BaseModel):
    id: int
    original_transaction_id: int
    user_id: int
    biller_id: int
    transaction_reference: str
    bill_type: str
    bill_amount: float
    transaction_fee: float
    total_amount: float
    cashback_amount: float
    cashback_rate: float
    account_number: str
    customer_name: Optional[str]
    bill_details: Optional[str]
    status: str
    payment_status: str
    external_reference: Optional[str]
    failure_reason: Optional[str]
    original_created_at: datetime
    original_updated_at: Optional[datetime]
    original_completed_at: Optional[datetime]
    archived_at: datetime
    archived_reason: str
    retention_until: Optional[datetime]
    user_email: Optional[str]
    biller_name: Optional[str]

    class Config:
        from_attributes = True


class ArchiveStatsResponse(BaseModel):
    total_archived_transactions: int
    status_breakdown: dict
    bill_type_breakdown: dict
    archive_reason_breakdown: dict
    total_archived_amount: float
    generated_at: str


@router.get("/transactions", response_model=List[ArchivedTransactionResponse])
async def get_user_archived_transactions(
    current_user: User = Depends(get_current_user),
    bill_type: Optional[str] = Query(None, description="Filter by bill type"),
    status: Optional[str] = Query(None, description="Filter by transaction status"),
    start_date: Optional[datetime] = Query(None, description="Filter from this date"),
    end_date: Optional[datetime] = Query(None, description="Filter until this date"),
    limit: int = Query(100, ge=1, le=1000, description="Number of records to return"),
    offset: int = Query(0, ge=0, description="Number of records to skip")
):
    """Get archived transactions for the current user."""
    archived_transactions = await ArchiveService.get_archived_transactions(
        user_id=current_user.id,
        bill_type=bill_type,
        status=status,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset
    )
    
    return archived_transactions


@router.get("/admin/transactions", response_model=List[ArchivedTransactionResponse])
async def get_all_archived_transactions(
    current_admin: User = Depends(get_current_admin_user),
    user_id: Optional[int] = Query(None, description="Filter by user ID"),
    bill_type: Optional[str] = Query(None, description="Filter by bill type"),
    status: Optional[str] = Query(None, description="Filter by transaction status"),
    start_date: Optional[datetime] = Query(None, description="Filter from this date"),
    end_date: Optional[datetime] = Query(None, description="Filter until this date"),
    limit: int = Query(100, ge=1, le=1000, description="Number of records to return"),
    offset: int = Query(0, ge=0, description="Number of records to skip")
):
    """Get all archived transactions (admin only)."""
    archived_transactions = await ArchiveService.get_archived_transactions(
        user_id=user_id,
        bill_type=bill_type,
        status=status,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset
    )
    
    return archived_transactions


@router.get("/admin/statistics", response_model=ArchiveStatsResponse)
async def get_archive_statistics(
    current_admin: User = Depends(get_current_admin_user)
):
    """Get archive statistics (admin only)."""
    stats = await ArchiveService.get_archive_statistics()
    return stats


@router.post("/admin/cleanup")
async def cleanup_expired_archives(
    current_admin: User = Depends(get_current_admin_user),
    retention_days: int = Query(2555, ge=1, description="Retention period in days")
):
    """Clean up archived transactions that have exceeded retention period (admin only)."""
    result = await ArchiveService.cleanup_expired_archives(retention_days)
    return result


@router.post("/admin/restore/{archive_id}")
async def restore_archived_transaction(
    archive_id: int,
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_database_session)
):
    """Restore an archived transaction back to active transactions (admin only)."""
    restored_transaction = await ArchiveService.restore_transaction(archive_id)
    
    if not restored_transaction:
        raise HTTPException(status_code=404, detail="Archived transaction not found")
    
    return {
        "message": "Transaction restored successfully",
        "restored_transaction_id": restored_transaction.id,
        "original_archive_id": archive_id
    }