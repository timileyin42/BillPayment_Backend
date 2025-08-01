from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, Path, Body
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database_model.cashback import Cashback, CashbackStatus, CashbackRule, CashbackRuleType
from app.database_model.transaction import Transaction
from app.database_model.user import User
from app.dependencies.get_db import get_db
from app.dependencies.auth import get_current_admin_user, require_permissions
from app.schemas.cashback import (
    CashbackRuleCreate, 
    CashbackRuleUpdate, 
    CashbackRuleResponse,
    CashbackResponse,
    CashbackAdminUpdate,
    CashbackStatistics
)
from app.services.cashback_service import CashbackService


router = APIRouter(prefix="/admin/cashback", tags=["admin", "cashback"])


@router.get("/rules", response_model=List[CashbackRuleResponse])
async def get_all_cashback_rules(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    status: Optional[bool] = Query(None, description="Filter by active status"),
    rule_type: Optional[CashbackRuleType] = Query(None, description="Filter by rule type"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin_user)
):
    """Get all cashback rules with optional filtering."""
    query = select(CashbackRule)
    
    if status is not None:
        query = query.where(CashbackRule.is_active == status)
    
    if rule_type is not None:
        query = query.where(CashbackRule.rule_type == rule_type)
    
    # Add pagination
    query = query.offset(skip).limit(limit)
    
    result = await db.execute(query)
    rules = result.scalars().all()
    
    return rules


@router.post("/rules", response_model=CashbackRuleResponse, status_code=201)
async def create_cashback_rule(
    rule_data: CashbackRuleCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(["manage_cashback"]))
):
    """Create a new cashback rule."""
    # Check for overlapping rules
    cashback_service = CashbackService(db)
    if await cashback_service.has_overlapping_rules(rule_data):
        raise HTTPException(
            status_code=400,
            detail="This rule overlaps with an existing rule. Please check rule conditions."
        )
    
    # Create the rule
    new_rule = CashbackRule(
        name=rule_data.name,
        description=rule_data.description,
        rule_type=rule_data.rule_type,
        percentage=rule_data.percentage,
        min_transaction_amount=rule_data.min_transaction_amount,
        max_cashback_amount=rule_data.max_cashback_amount,
        conditions=rule_data.conditions,
        is_active=rule_data.is_active,
        start_date=rule_data.start_date,
        end_date=rule_data.end_date
    )
    
    db.add(new_rule)
    await db.commit()
    await db.refresh(new_rule)
    
    return new_rule


@router.get("/rules/{rule_id}", response_model=CashbackRuleResponse)
async def get_cashback_rule(
    rule_id: int = Path(...),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin_user)
):
    """Get a specific cashback rule by ID."""
    result = await db.execute(select(CashbackRule).where(CashbackRule.id == rule_id))
    rule = result.scalar_one_or_none()
    
    if not rule:
        raise HTTPException(status_code=404, detail="Cashback rule not found")
    
    return rule


@router.put("/rules/{rule_id}", response_model=CashbackRuleResponse)
async def update_cashback_rule(
    rule_data: CashbackRuleUpdate,
    rule_id: int = Path(...),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(["manage_cashback"]))
):
    """Update an existing cashback rule."""
    result = await db.execute(select(CashbackRule).where(CashbackRule.id == rule_id))
    rule = result.scalar_one_or_none()
    
    if not rule:
        raise HTTPException(status_code=404, detail="Cashback rule not found")
    
    # Check for overlapping rules if changing conditions
    cashback_service = CashbackService(db)
    if (rule_data.rule_type != rule.rule_type or 
        rule_data.conditions != rule.conditions) and \
       await cashback_service.has_overlapping_rules(rule_data, exclude_id=rule_id):
        raise HTTPException(
            status_code=400,
            detail="This rule would overlap with an existing rule. Please check rule conditions."
        )
    
    # Update rule fields
    update_data = rule_data.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(rule, key, value)
    
    await db.commit()
    await db.refresh(rule)
    
    return rule


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_cashback_rule(
    rule_id: int = Path(...),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(["manage_cashback"]))
):
    """Delete a cashback rule."""
    result = await db.execute(select(CashbackRule).where(CashbackRule.id == rule_id))
    rule = result.scalar_one_or_none()
    
    if not rule:
        raise HTTPException(status_code=404, detail="Cashback rule not found")
    
    # Instead of hard delete, we'll mark it as inactive and set end date
    rule.is_active = False
    rule.end_date = datetime.utcnow()
    
    await db.commit()
    
    return None


@router.get("/awarded", response_model=List[CashbackResponse])
async def get_awarded_cashbacks(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    user_id: Optional[int] = Query(None, description="Filter by user ID"),
    status: Optional[CashbackStatus] = Query(None, description="Filter by cashback status"),
    from_date: Optional[datetime] = Query(None, description="Filter from this date"),
    to_date: Optional[datetime] = Query(None, description="Filter to this date"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin_user)
):
    """Get all awarded cashbacks with optional filtering."""
    query = select(Cashback)
    
    if user_id is not None:
        query = query.where(Cashback.user_id == user_id)
    
    if status is not None:
        query = query.where(Cashback.status == status)
    
    if from_date is not None:
        query = query.where(Cashback.created_at >= from_date)
    
    if to_date is not None:
        query = query.where(Cashback.created_at <= to_date)
    
    # Add pagination
    query = query.offset(skip).limit(limit)
    
    result = await db.execute(query)
    cashbacks = result.scalars().all()
    
    return cashbacks


@router.get("/awarded/{cashback_id}", response_model=CashbackResponse)
async def get_cashback_detail(
    cashback_id: int = Path(...),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin_user)
):
    """Get detailed information about a specific cashback."""
    result = await db.execute(select(Cashback).where(Cashback.id == cashback_id))
    cashback = result.scalar_one_or_none()
    
    if not cashback:
        raise HTTPException(status_code=404, detail="Cashback not found")
    
    return cashback


@router.put("/awarded/{cashback_id}", response_model=CashbackResponse)
async def update_cashback_status(
    cashback_update: CashbackAdminUpdate,
    cashback_id: int = Path(...),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(["manage_cashback"]))
):
    """Update the status of a cashback award."""
    result = await db.execute(select(Cashback).where(Cashback.id == cashback_id))
    cashback = result.scalar_one_or_none()
    
    if not cashback:
        raise HTTPException(status_code=404, detail="Cashback not found")
    
    # Update status and add admin notes
    cashback.status = cashback_update.status
    
    if cashback_update.admin_notes:
        cashback.admin_notes = cashback_update.admin_notes
    
    # If status is changed to CREDITED, set credited date
    if cashback_update.status == CashbackStatus.CREDITED and not cashback.credited_date:
        cashback.credited_date = datetime.utcnow()
    
    # If status is changed to REJECTED, set rejection reason
    if cashback_update.status == CashbackStatus.REJECTED:
        cashback.rejection_reason = cashback_update.rejection_reason
    
    # Update metadata
    if not cashback.metadata:
        cashback.metadata = {}
    
    cashback.metadata["admin_updated"] = {
        "timestamp": datetime.utcnow().isoformat(),
        "previous_status": cashback.status.value,
        "new_status": cashback_update.status.value
    }
    
    await db.commit()
    await db.refresh(cashback)
    
    # If status changed to CREDITED, process the cashback credit
    if cashback_update.status == CashbackStatus.CREDITED and cashback_update.process_credit:
        cashback_service = CashbackService(db)
        await cashback_service.process_cashback_credit(cashback)
    
    return cashback


@router.get("/statistics", response_model=CashbackStatistics)
async def get_cashback_statistics(
    period: str = Query("month", description="Statistics period: day, week, month, year, all"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin_user)
):
    """Get cashback statistics for the specified period."""
    # Determine date range based on period
    now = datetime.utcnow()
    from_date = None
    
    if period == "day":
        from_date = now - timedelta(days=1)
    elif period == "week":
        from_date = now - timedelta(weeks=1)
    elif period == "month":
        from_date = now - timedelta(days=30)
    elif period == "year":
        from_date = now - timedelta(days=365)
    
    # Base query with date filter if applicable
    base_query = select(Cashback)
    if from_date:
        base_query = base_query.where(Cashback.created_at >= from_date)
    
    # Total cashback amount awarded
    total_query = select(func.sum(Cashback.amount))
    if from_date:
        total_query = total_query.where(Cashback.created_at >= from_date)
    
    total_result = await db.execute(total_query)
    total_amount = total_result.scalar() or 0
    
    # Count by status
    status_counts = {}
    for status in CashbackStatus:
        count_query = select(func.count()).select_from(Cashback).where(Cashback.status == status)
        if from_date:
            count_query = count_query.where(Cashback.created_at >= from_date)
        
        count_result = await db.execute(count_query)
        status_counts[status.value] = count_result.scalar()
    
    # Amount by status
    status_amounts = {}
    for status in CashbackStatus:
        amount_query = select(func.sum(Cashback.amount)).select_from(Cashback).where(Cashback.status == status)
        if from_date:
            amount_query = amount_query.where(Cashback.created_at >= from_date)
        
        amount_result = await db.execute(amount_query)
        status_amounts[status.value] = float(amount_result.scalar() or 0)
    
    # Top users by cashback amount
    top_users_query = select(
        Cashback.user_id,
        func.sum(Cashback.amount).label("total_amount"),
        func.count().label("count")
    ).group_by(Cashback.user_id).order_by(func.sum(Cashback.amount).desc()).limit(10)
    
    if from_date:
        top_users_query = top_users_query.where(Cashback.created_at >= from_date)
    
    top_users_result = await db.execute(top_users_query)
    top_users = [{
        "user_id": row.user_id,
        "total_amount": float(row.total_amount),
        "count": row.count
    } for row in top_users_result]
    
    # Top rules by usage
    top_rules_query = select(
        Cashback.rule_id,
        func.count().label("count"),
        func.sum(Cashback.amount).label("total_amount")
    ).where(Cashback.rule_id.isnot(None)).group_by(Cashback.rule_id).order_by(func.count().desc()).limit(10)
    
    if from_date:
        top_rules_query = top_rules_query.where(Cashback.created_at >= from_date)
    
    top_rules_result = await db.execute(top_rules_query)
    top_rules_raw = [(row.rule_id, row.count, row.total_amount) for row in top_rules_result]
    
    # Get rule names
    top_rules = []
    for rule_id, count, amount in top_rules_raw:
        rule_query = select(CashbackRule.name).where(CashbackRule.id == rule_id)
        rule_result = await db.execute(rule_query)
        rule_name = rule_result.scalar() or f"Rule {rule_id}"
        
        top_rules.append({
            "rule_id": rule_id,
            "rule_name": rule_name,
            "count": count,
            "total_amount": float(amount)
        })
    
    return {
        "period": period,
        "from_date": from_date,
        "to_date": now,
        "total_amount": float(total_amount),
        "status_counts": status_counts,
        "status_amounts": status_amounts,
        "top_users": top_users,
        "top_rules": top_rules
    }


@router.post("/recalculate", response_model=Dict[str, Any])
async def recalculate_cashbacks(
    transaction_ids: List[int] = Body(..., description="List of transaction IDs to recalculate cashback for"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(["manage_cashback"]))
):
    """Recalculate cashback for specified transactions."""
    cashback_service = CashbackService(db)
    results = []
    
    for transaction_id in transaction_ids:
        # Get transaction
        transaction_result = await db.execute(
            select(Transaction).where(Transaction.id == transaction_id)
        )
        transaction = transaction_result.scalar_one_or_none()
        
        if not transaction:
            results.append({
                "transaction_id": transaction_id,
                "success": False,
                "error": "Transaction not found"
            })
            continue
        
        try:
            # Recalculate cashback
            cashback = await cashback_service.calculate_and_award_cashback(
                transaction=transaction,
                force_recalculation=True
            )
            
            results.append({
                "transaction_id": transaction_id,
                "success": True,
                "cashback_id": cashback.id if cashback else None,
                "amount": float(cashback.amount) if cashback else 0
            })
        except Exception as e:
            results.append({
                "transaction_id": transaction_id,
                "success": False,
                "error": str(e)
            })
    
    return {
        "total": len(transaction_ids),
        "successful": sum(1 for r in results if r["success"]),
        "failed": sum(1 for r in results if not r["success"]),
        "results": results
    }


@router.post("/bulk-update", response_model=Dict[str, Any])
async def bulk_update_cashbacks(
    cashback_ids: List[int] = Body(..., description="List of cashback IDs to update"),
    status: CashbackStatus = Body(..., description="New status to set"),
    process_credits: bool = Body(False, description="Whether to process credits for CREDITED status"),
    admin_notes: Optional[str] = Body(None, description="Admin notes to add"),
    rejection_reason: Optional[str] = Body(None, description="Rejection reason if status is REJECTED"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(["manage_cashback"]))
):
    """Bulk update cashback statuses."""
    results = []
    cashback_service = CashbackService(db)
    
    for cashback_id in cashback_ids:
        # Get cashback
        cashback_result = await db.execute(
            select(Cashback).where(Cashback.id == cashback_id)
        )
        cashback = cashback_result.scalar_one_or_none()
        
        if not cashback:
            results.append({
                "cashback_id": cashback_id,
                "success": False,
                "error": "Cashback not found"
            })
            continue
        
        try:
            # Update status
            previous_status = cashback.status
            cashback.status = status
            
            if admin_notes:
                cashback.admin_notes = admin_notes
            
            # If status is changed to CREDITED, set credited date
            if status == CashbackStatus.CREDITED and not cashback.credited_date:
                cashback.credited_date = datetime.utcnow()
            
            # If status is changed to REJECTED, set rejection reason
            if status == CashbackStatus.REJECTED and rejection_reason:
                cashback.rejection_reason = rejection_reason
            
            # Update metadata
            if not cashback.metadata:
                cashback.metadata = {}
            
            cashback.metadata["admin_bulk_updated"] = {
                "timestamp": datetime.utcnow().isoformat(),
                "previous_status": previous_status.value,
                "new_status": status.value
            }
            
            await db.commit()
            
            # If status changed to CREDITED and process_credits is True, process the cashback credit
            if status == CashbackStatus.CREDITED and process_credits:
                await cashback_service.process_cashback_credit(cashback)
            
            results.append({
                "cashback_id": cashback_id,
                "success": True,
                "previous_status": previous_status.value,
                "new_status": status.value
            })
        except Exception as e:
            results.append({
                "cashback_id": cashback_id,
                "success": False,
                "error": str(e)
            })
    
    return {
        "total": len(cashback_ids),
        "successful": sum(1 for r in results if r["success"]),
        "failed": sum(1 for r in results if not r["success"]),
        "results": results
    }