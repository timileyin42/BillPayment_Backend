from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from pydantic import BaseModel, Field

from app.core.database import get_db
from app.core.security import get_current_admin_user
from app.database_model.user import User
from app.database_model.wallet import Wallet, WalletTransaction
from app.database_model.transaction import Transaction, RecurringPayment
from app.database_model.cashback import Cashback, CashbackRule, ReferralReward
from app.database_model.biller import Biller, BillerStatus
from app.services.user_service import UserService
from app.services.wallet_service import WalletService
from app.services.payment_service import PaymentService
from app.services.cashback_service import CashbackService
from app.core.errors import NotFoundError, ValidationError

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


# Pydantic Models
class AdminDashboardResponse(BaseModel):
    total_users: int
    active_users: int
    total_transactions: int
    total_transaction_volume: float
    total_cashback_paid: float
    total_wallet_balance: float
    recent_transactions: List[Dict[str, Any]]
    top_billers: List[Dict[str, Any]]
    daily_stats: List[Dict[str, Any]]


class UserManagementResponse(BaseModel):
    id: int
    email: str
    phone: str
    first_name: str
    last_name: str
    is_verified: bool
    is_active: bool
    is_admin: bool
    wallet_balance: float
    total_transactions: int
    total_spent: float
    total_cashback: float
    created_at: datetime
    last_login: Optional[datetime]
    
    class Config:
        from_attributes = True


class TransactionManagementResponse(BaseModel):
    id: int
    user_id: int
    user_email: str
    biller_code: str
    biller_name: str
    amount: float
    fee: float
    cashback_amount: float
    status: str
    reference: str
    external_reference: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class CashbackRuleCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=1, max_length=500)
    cashback_percentage: float = Field(..., ge=0, le=100)
    min_amount: Optional[float] = Field(None, ge=0)
    max_amount: Optional[float] = Field(None, ge=0)
    max_cashback_per_transaction: Optional[float] = Field(None, ge=0)
    max_cashback_per_month: Optional[float] = Field(None, ge=0)
    bill_type: Optional[str] = None
    biller_code: Optional[str] = None
    is_active: bool = True
    priority: int = Field(1, ge=1, le=10)


class CashbackRuleUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, min_length=1, max_length=500)
    cashback_percentage: Optional[float] = Field(None, ge=0, le=100)
    min_amount: Optional[float] = Field(None, ge=0)
    max_amount: Optional[float] = Field(None, ge=0)
    max_cashback_per_transaction: Optional[float] = Field(None, ge=0)
    max_cashback_per_month: Optional[float] = Field(None, ge=0)
    bill_type: Optional[str] = None
    biller_code: Optional[str] = None
    is_active: Optional[bool] = None
    priority: Optional[int] = Field(None, ge=1, le=10)


class BulkActionRequest(BaseModel):
    user_ids: List[int]
    action: str = Field(..., regex="^(activate|deactivate|verify|unverify)$")
    reason: Optional[str] = None


class ManualCashbackRequest(BaseModel):
    user_id: int
    amount: float = Field(..., gt=0)
    description: str = Field(..., min_length=1, max_length=200)
    cashback_type: str = "manual"


@router.get("/dashboard", response_model=AdminDashboardResponse)
async def get_admin_dashboard(
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=1, le=365)
):
    """Get admin dashboard with key metrics and statistics."""
    try:
        # Calculate date range
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Total users
        total_users_result = await db.execute(select(func.count(User.id)))
        total_users = total_users_result.scalar()
        
        # Active users (logged in within last 30 days)
        active_users_result = await db.execute(
            select(func.count(User.id)).where(
                User.last_login >= datetime.utcnow() - timedelta(days=30)
            )
        )
        active_users = active_users_result.scalar() or 0
        
        # Total transactions
        total_transactions_result = await db.execute(select(func.count(Transaction.id)))
        total_transactions = total_transactions_result.scalar()
        
        # Total transaction volume
        total_volume_result = await db.execute(select(func.sum(Transaction.amount)))
        total_transaction_volume = float(total_volume_result.scalar() or 0)
        
        # Total cashback paid
        total_cashback_result = await db.execute(
            select(func.sum(Cashback.amount)).where(Cashback.status == "credited")
        )
        total_cashback_paid = float(total_cashback_result.scalar() or 0)
        
        # Total wallet balance
        total_wallet_result = await db.execute(select(func.sum(Wallet.main_balance)))
        total_wallet_balance = float(total_wallet_result.scalar() or 0)
        
        # Recent transactions (last 10)
        recent_transactions_result = await db.execute(
            select(Transaction, User.email, Biller.name)
            .join(User, Transaction.user_id == User.id)
            .join(Biller, Transaction.biller_code == Biller.code)
            .order_by(Transaction.created_at.desc())
            .limit(10)
        )
        
        recent_transactions = []
        for transaction, user_email, biller_name in recent_transactions_result:
            recent_transactions.append({
                "id": transaction.id,
                "user_email": user_email,
                "biller_name": biller_name,
                "amount": float(transaction.amount),
                "status": transaction.status,
                "created_at": transaction.created_at
            })
        
        # Top billers by transaction count
        top_billers_result = await db.execute(
            select(
                Biller.name,
                Biller.code,
                func.count(Transaction.id).label("transaction_count"),
                func.sum(Transaction.amount).label("total_volume")
            )
            .join(Transaction, Biller.code == Transaction.biller_code)
            .group_by(Biller.id, Biller.name, Biller.code)
            .order_by(func.count(Transaction.id).desc())
            .limit(5)
        )
        
        top_billers = []
        for name, code, count, volume in top_billers_result:
            top_billers.append({
                "name": name,
                "code": code,
                "transaction_count": count,
                "total_volume": float(volume or 0)
            })
        
        # Daily stats for the last 7 days
        daily_stats = []
        for i in range(7):
            day_start = (datetime.utcnow() - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            
            daily_transactions_result = await db.execute(
                select(
                    func.count(Transaction.id).label("count"),
                    func.sum(Transaction.amount).label("volume")
                ).where(
                    and_(
                        Transaction.created_at >= day_start,
                        Transaction.created_at < day_end
                    )
                )
            )
            
            count, volume = daily_transactions_result.first()
            daily_stats.append({
                "date": day_start.date().isoformat(),
                "transaction_count": count or 0,
                "transaction_volume": float(volume or 0)
            })
        
        return AdminDashboardResponse(
            total_users=total_users,
            active_users=active_users,
            total_transactions=total_transactions,
            total_transaction_volume=total_transaction_volume,
            total_cashback_paid=total_cashback_paid,
            total_wallet_balance=total_wallet_balance,
            recent_transactions=recent_transactions,
            top_billers=top_billers,
            daily_stats=daily_stats
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users", response_model=List[UserManagementResponse])
async def get_users(
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    is_verified: Optional[bool] = Query(None)
):
    """Get users with filtering and search options."""
    try:
        query = select(
            User,
            Wallet.main_balance,
            func.count(Transaction.id).label("transaction_count"),
            func.sum(Transaction.amount).label("total_spent"),
            func.sum(Cashback.amount).label("total_cashback")
        ).outerjoin(
            Wallet, User.id == Wallet.user_id
        ).outerjoin(
            Transaction, User.id == Transaction.user_id
        ).outerjoin(
            Cashback, and_(User.id == Cashback.user_id, Cashback.status == "credited")
        ).group_by(User.id, Wallet.main_balance)
        
        # Apply filters
        if search:
            query = query.where(
                or_(
                    User.email.ilike(f"%{search}%"),
                    User.first_name.ilike(f"%{search}%"),
                    User.last_name.ilike(f"%{search}%"),
                    User.phone.ilike(f"%{search}%")
                )
            )
        
        if is_active is not None:
            query = query.where(User.is_active == is_active)
        
        if is_verified is not None:
            query = query.where(User.is_verified == is_verified)
        
        query = query.offset(offset).limit(limit)
        
        result = await db.execute(query)
        users_data = result.all()
        
        users = []
        for user, wallet_balance, transaction_count, total_spent, total_cashback in users_data:
            users.append(UserManagementResponse(
                id=user.id,
                email=user.email,
                phone=user.phone,
                first_name=user.first_name,
                last_name=user.last_name,
                is_verified=user.is_verified,
                is_active=user.is_active,
                is_admin=user.is_admin,
                wallet_balance=float(wallet_balance or 0),
                total_transactions=transaction_count or 0,
                total_spent=float(total_spent or 0),
                total_cashback=float(total_cashback or 0),
                created_at=user.created_at,
                last_login=user.last_login
            ))
        
        return users
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/transactions", response_model=List[TransactionManagementResponse])
async def get_transactions(
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None),
    biller_code: Optional[str] = Query(None),
    user_id: Optional[int] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None)
):
    """Get transactions with filtering options."""
    try:
        query = select(
            Transaction,
            User.email,
            Biller.name
        ).join(
            User, Transaction.user_id == User.id
        ).join(
            Biller, Transaction.biller_code == Biller.code
        )
        
        # Apply filters
        if status:
            query = query.where(Transaction.status == status)
        
        if biller_code:
            query = query.where(Transaction.biller_code == biller_code)
        
        if user_id:
            query = query.where(Transaction.user_id == user_id)
        
        if start_date:
            query = query.where(Transaction.created_at >= start_date)
        
        if end_date:
            query = query.where(Transaction.created_at <= end_date)
        
        query = query.order_by(Transaction.created_at.desc()).offset(offset).limit(limit)
        
        result = await db.execute(query)
        transactions_data = result.all()
        
        transactions = []
        for transaction, user_email, biller_name in transactions_data:
            transactions.append(TransactionManagementResponse(
                id=transaction.id,
                user_id=transaction.user_id,
                user_email=user_email,
                biller_code=transaction.biller_code,
                biller_name=biller_name,
                amount=float(transaction.amount),
                fee=float(transaction.fee),
                cashback_amount=float(transaction.cashback_amount),
                status=transaction.status,
                reference=transaction.reference,
                external_reference=transaction.external_reference,
                created_at=transaction.created_at,
                completed_at=transaction.completed_at
            ))
        
        return transactions
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cashback-rules")
async def create_cashback_rule(
    rule_data: CashbackRuleCreateRequest,
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new cashback rule."""
    try:
        cashback_service = CashbackService(db)
        
        rule = await cashback_service.create_cashback_rule(
            name=rule_data.name,
            description=rule_data.description,
            cashback_percentage=rule_data.cashback_percentage,
            min_amount=rule_data.min_amount,
            max_amount=rule_data.max_amount,
            max_cashback_per_transaction=rule_data.max_cashback_per_transaction,
            max_cashback_per_month=rule_data.max_cashback_per_month,
            bill_type=rule_data.bill_type,
            biller_code=rule_data.biller_code,
            is_active=rule_data.is_active,
            priority=rule_data.priority
        )
        
        return {"message": "Cashback rule created successfully", "rule_id": rule.id}
        
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/cashback-rules/{rule_id}")
async def update_cashback_rule(
    rule_id: int,
    rule_data: CashbackRuleUpdateRequest,
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Update an existing cashback rule."""
    try:
        cashback_service = CashbackService(db)
        
        rule = await cashback_service.update_cashback_rule(
            rule_id=rule_id,
            **rule_data.dict(exclude_unset=True)
        )
        
        if not rule:
            raise HTTPException(status_code=404, detail="Cashback rule not found")
        
        return {"message": "Cashback rule updated successfully", "rule_id": rule.id}
        
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Cashback rule not found")
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/cashback-rules/{rule_id}")
async def delete_cashback_rule(
    rule_id: int,
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a cashback rule."""
    try:
        cashback_service = CashbackService(db)
        
        success = await cashback_service.delete_cashback_rule(rule_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="Cashback rule not found")
        
        return {"message": "Cashback rule deleted successfully"}
        
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Cashback rule not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/users/bulk-action")
async def bulk_user_action(
    action_data: BulkActionRequest,
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Perform bulk actions on users."""
    try:
        user_service = UserService(db)
        
        results = []
        for user_id in action_data.user_ids:
            try:
                if action_data.action == "activate":
                    await user_service.activate_user(user_id)
                elif action_data.action == "deactivate":
                    await user_service.deactivate_user(user_id, action_data.reason)
                elif action_data.action == "verify":
                    await user_service.verify_user(user_id)
                elif action_data.action == "unverify":
                    await user_service.unverify_user(user_id)
                
                results.append({"user_id": user_id, "status": "success"})
            except Exception as e:
                results.append({"user_id": user_id, "status": "failed", "error": str(e)})
        
        return {
            "message": f"Bulk {action_data.action} completed",
            "results": results
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cashback/manual")
async def create_manual_cashback(
    cashback_data: ManualCashbackRequest,
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Create manual cashback for a user."""
    try:
        cashback_service = CashbackService(db)
        
        cashback = await cashback_service.create_manual_cashback(
            user_id=cashback_data.user_id,
            amount=cashback_data.amount,
            description=cashback_data.description,
            admin_id=current_admin.id
        )
        
        return {
            "message": "Manual cashback created successfully",
            "cashback_id": cashback.id,
            "amount": float(cashback.amount)
        }
        
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reports/financial")
async def get_financial_report(
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
    start_date: datetime = Query(...),
    end_date: datetime = Query(...),
    group_by: str = Query("day", regex="^(day|week|month)$")
):
    """Generate financial reports for the specified period."""
    try:
        # This would typically be implemented with more sophisticated reporting logic
        # For now, providing basic aggregated data
        
        # Transaction volume and count
        transaction_stats = await db.execute(
            select(
                func.count(Transaction.id).label("total_transactions"),
                func.sum(Transaction.amount).label("total_volume"),
                func.sum(Transaction.fee).label("total_fees"),
                func.sum(Transaction.cashback_amount).label("total_cashback")
            ).where(
                and_(
                    Transaction.created_at >= start_date,
                    Transaction.created_at <= end_date
                )
            )
        )
        
        stats = transaction_stats.first()
        
        return {
            "period": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat()
            },
            "summary": {
                "total_transactions": stats.total_transactions or 0,
                "total_volume": float(stats.total_volume or 0),
                "total_fees": float(stats.total_fees or 0),
                "total_cashback": float(stats.total_cashback or 0),
                "net_revenue": float((stats.total_fees or 0) - (stats.total_cashback or 0))
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))