from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, validator
from datetime import datetime, timedelta

from ..core.database import get_database_session
from ..database_model.biller import Biller, BillerStatus
from ..payment_model.provider_factory import BillerProviderFactory
from .auth import get_current_user, get_current_admin_user

router = APIRouter(prefix="/billers", tags=["Billers"])

# Pydantic models for request/response
class BillerResponse(BaseModel):
    id: int
    name: str
    code: str
    bill_type: str
    category: str
    description: str
    logo_url: str = None
    min_amount: float
    max_amount: float
    convenience_fee_type: str
    convenience_fee_value: float
    cashback_rate: float
    processing_time_minutes: int
    is_active: bool
    supports_validation: bool
    validation_pattern: str = None

class BillerStatusResponse(BaseModel):
    biller_id: int
    biller_name: str
    status: str
    response_time_ms: int = None
    success_rate: float = None
    last_checked: str
    error_message: str = None

class BillerCreateRequest(BaseModel):
    name: str
    code: str
    bill_type: str
    category: str
    description: str = None
    logo_url: str = None
    api_endpoint: str
    api_key: str = None
    api_username: str = None
    api_password: str = None
    min_amount: float = 50.0
    max_amount: float = 1000000.0
    convenience_fee_type: str = "percentage"
    convenience_fee_value: float = 0.0
    cashback_rate: float = 0.01
    processing_time_minutes: int = 5
    supports_validation: bool = True
    validation_pattern: str = None
    
    @validator('bill_type')
    def validate_bill_type(cls, v):
        allowed_types = ['electricity', 'internet', 'cable_tv', 'airtime', 'data', 'water', 'waste', 'education']
        if v not in allowed_types:
            raise ValueError(f'Bill type must be one of: {", ".join(allowed_types)}')
        return v
    
    @validator('convenience_fee_type')
    def validate_fee_type(cls, v):
        allowed_types = ['fixed', 'percentage']
        if v not in allowed_types:
            raise ValueError(f'Fee type must be one of: {", ".join(allowed_types)}')
        return v
    
    @validator('cashback_rate')
    def validate_cashback_rate(cls, v):
        if v < 0 or v > 0.1:  # Max 10% cashback
            raise ValueError('Cashback rate must be between 0 and 0.1 (10%)')
        return v

class BillerUpdateRequest(BaseModel):
    name: str = None
    description: str = None
    logo_url: str = None
    min_amount: float = None
    max_amount: float = None
    convenience_fee_type: str = None
    convenience_fee_value: float = None
    cashback_rate: float = None
    processing_time_minutes: int = None
    is_active: bool = None
    supports_validation: bool = None
    validation_pattern: str = None

@router.get("/", response_model=List[BillerResponse])
async def get_billers(
    db: AsyncSession = Depends(get_database_session),
    bill_type: Optional[str] = Query(None, description="Filter by bill type"),
    category: Optional[str] = Query(None, description="Filter by category"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    search: Optional[str] = Query(None, description="Search by name or code")
):
    """Get list of available billers."""
    try:
        query = select(Biller)
        
        # Apply filters
        conditions = []
        
        if bill_type:
            conditions.append(Biller.bill_type == bill_type)
        
        if category:
            conditions.append(Biller.category == category)
        
        if is_active is not None:
            conditions.append(Biller.is_active == is_active)
        
        if search:
            search_term = f"%{search}%"
            conditions.append(
                or_(
                    Biller.name.ilike(search_term),
                    Biller.code.ilike(search_term)
                )
            )
        
        if conditions:
            query = query.where(and_(*conditions))
        
        query = query.order_by(Biller.name)
        
        result = await db.execute(query)
        billers = result.scalars().all()
        
        return [
            BillerResponse(
                id=biller.id,
                name=biller.name,
                code=biller.code,
                bill_type=biller.bill_type,
                category=biller.category,
                description=biller.description or "",
                logo_url=biller.logo_url,
                min_amount=float(biller.min_amount),
                max_amount=float(biller.max_amount),
                convenience_fee_type=biller.convenience_fee_type,
                convenience_fee_value=float(biller.convenience_fee_value),
                cashback_rate=float(biller.cashback_rate),
                processing_time_minutes=biller.processing_time_minutes,
                is_active=biller.is_active,
                supports_validation=biller.supports_validation,
                validation_pattern=biller.validation_pattern
            )
            for biller in billers
        ]
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve billers"
        )

@router.get("/categories", response_model=List[str])
async def get_biller_categories(
    db: AsyncSession = Depends(get_database_session)
):
    """Get list of available biller categories."""
    try:
        result = await db.execute(
            select(Biller.category).distinct().where(Biller.is_active == True)
        )
        categories = [row[0] for row in result.all()]
        return sorted(categories)
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve biller categories"
        )

@router.get("/types", response_model=List[str])
async def get_bill_types(
    db: AsyncSession = Depends(get_database_session)
):
    """Get list of available bill types."""
    try:
        result = await db.execute(
            select(Biller.bill_type).distinct().where(Biller.is_active == True)
        )
        bill_types = [row[0] for row in result.all()]
        return sorted(bill_types)
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve bill types"
        )

@router.get("/{biller_code}", response_model=BillerResponse)
async def get_biller_details(
    biller_code: str,
    db: AsyncSession = Depends(get_database_session)
):
    """Get specific biller details."""
    try:
        result = await db.execute(
            select(Biller).where(Biller.code == biller_code)
        )
        biller = result.scalar_one_or_none()
        
        if not biller:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Biller not found"
            )
        
        return BillerResponse(
            id=biller.id,
            name=biller.name,
            code=biller.code,
            bill_type=biller.bill_type,
            category=biller.category,
            description=biller.description or "",
            logo_url=biller.logo_url,
            min_amount=float(biller.min_amount),
            max_amount=float(biller.max_amount),
            convenience_fee_type=biller.convenience_fee_type,
            convenience_fee_value=float(biller.convenience_fee_value),
            cashback_rate=float(biller.cashback_rate),
            processing_time_minutes=biller.processing_time_minutes,
            is_active=biller.is_active,
            supports_validation=biller.supports_validation,
            validation_pattern=biller.validation_pattern
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve biller details"
        )

@router.get("/status/all", response_model=List[BillerStatusResponse])
async def get_all_biller_status(
    db: AsyncSession = Depends(get_database_session),
    current_user = Depends(get_current_user)
):
    """Get status of all billers."""
    try:
        # Get latest status for each biller
        subquery = (
            select(
                BillerStatus.biller_id,
                func.max(BillerStatus.last_checked).label("latest_check")
            )
            .group_by(BillerStatus.biller_id)
            .subquery()
        )
        
        result = await db.execute(
            select(BillerStatus, Biller.name)
            .join(Biller, BillerStatus.biller_id == Biller.id)
            .join(
                subquery,
                and_(
                    BillerStatus.biller_id == subquery.c.biller_id,
                    BillerStatus.last_checked == subquery.c.latest_check
                )
            )
            .where(Biller.is_active == True)
        )
        
        status_records = result.all()
        
        return [
            BillerStatusResponse(
                biller_id=status.BillerStatus.biller_id,
                biller_name=status.name,
                status=status.BillerStatus.status,
                response_time_ms=status.BillerStatus.response_time_ms,
                success_rate=float(status.BillerStatus.success_rate or 0),
                last_checked=status.BillerStatus.last_checked.isoformat(),
                error_message=status.BillerStatus.error_message
            )
            for status in status_records
        ]
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve biller status"
        )

@router.get("/status/{biller_code}", response_model=BillerStatusResponse)
async def get_biller_status(
    biller_code: str,
    db: AsyncSession = Depends(get_database_session),
    current_user = Depends(get_current_user)
):
    """Get specific biller status."""
    try:
        # Get biller
        biller_result = await db.execute(
            select(Biller).where(Biller.code == biller_code)
        )
        biller = biller_result.scalar_one_or_none()
        
        if not biller:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Biller not found"
            )
        
        # Get latest status
        status_result = await db.execute(
            select(BillerStatus)
            .where(BillerStatus.biller_id == biller.id)
            .order_by(BillerStatus.last_checked.desc())
            .limit(1)
        )
        
        biller_status = status_result.scalar_one_or_none()
        
        if not biller_status:
            # No status record found, return default
            return BillerStatusResponse(
                biller_id=biller.id,
                biller_name=biller.name,
                status="unknown",
                last_checked=datetime.utcnow().isoformat()
            )
        
        return BillerStatusResponse(
            biller_id=biller_status.biller_id,
            biller_name=biller.name,
            status=biller_status.status,
            response_time_ms=biller_status.response_time_ms,
            success_rate=float(biller_status.success_rate or 0),
            last_checked=biller_status.last_checked.isoformat(),
            error_message=biller_status.error_message
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve biller status"
        )

@router.post("/check-status/{biller_code}", response_model=BillerStatusResponse)
async def check_biller_status(
    biller_code: str,
    db: AsyncSession = Depends(get_database_session),
    current_user = Depends(get_current_user)
):
    """Manually check biller status."""
    try:
        # Get biller
        biller_result = await db.execute(
            select(Biller).where(Biller.code == biller_code)
        )
        biller = biller_result.scalar_one_or_none()
        
        if not biller:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Biller not found"
            )
        
        # Create provider instance
        provider_config = {
            "name": biller.name,
            "api_endpoint": biller.api_endpoint,
            "api_key": biller.api_key,
            "api_username": biller.api_username,
            "api_password": biller.api_password
        }
        
        provider = BillerProviderFactory.create_biller(biller.code, provider_config)
        
        # Check service status
        start_time = datetime.utcnow()
        try:
            status_info = await provider.get_service_status()
            end_time = datetime.utcnow()
            
            response_time = int((end_time - start_time).total_seconds() * 1000)
            
            # Create status record
            biller_status = BillerStatus(
                biller_id=biller.id,
                status=status_info.get("status", "operational"),
                response_time_ms=response_time,
                last_checked=datetime.utcnow()
            )
            
        except Exception as e:
            end_time = datetime.utcnow()
            response_time = int((end_time - start_time).total_seconds() * 1000)
            
            # Create error status record
            biller_status = BillerStatus(
                biller_id=biller.id,
                status="error",
                response_time_ms=response_time,
                error_message=str(e),
                last_checked=datetime.utcnow()
            )
        
        db.add(biller_status)
        await db.commit()
        
        return BillerStatusResponse(
            biller_id=biller_status.biller_id,
            biller_name=biller.name,
            status=biller_status.status,
            response_time_ms=biller_status.response_time_ms,
            last_checked=biller_status.last_checked.isoformat(),
            error_message=biller_status.error_message
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to check biller status"
        )

# Admin endpoints
@router.post("/", response_model=BillerResponse)
async def create_biller(
    biller_data: BillerCreateRequest,
    current_admin = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_database_session)
):
    """Create new biller (Admin only)."""
    try:
        # Check if biller code already exists
        existing_result = await db.execute(
            select(Biller).where(Biller.code == biller_data.code)
        )
        existing_biller = existing_result.scalar_one_or_none()
        
        if existing_biller:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Biller with this code already exists"
            )
        
        # Create new biller
        biller = Biller(
            name=biller_data.name,
            code=biller_data.code,
            bill_type=biller_data.bill_type,
            category=biller_data.category,
            description=biller_data.description,
            logo_url=biller_data.logo_url,
            api_endpoint=biller_data.api_endpoint,
            api_key=biller_data.api_key,
            api_username=biller_data.api_username,
            api_password=biller_data.api_password,
            min_amount=biller_data.min_amount,
            max_amount=biller_data.max_amount,
            convenience_fee_type=biller_data.convenience_fee_type,
            convenience_fee_value=biller_data.convenience_fee_value,
            cashback_rate=biller_data.cashback_rate,
            processing_time_minutes=biller_data.processing_time_minutes,
            supports_validation=biller_data.supports_validation,
            validation_pattern=biller_data.validation_pattern
        )
        
        db.add(biller)
        await db.commit()
        await db.refresh(biller)
        
        return BillerResponse(
            id=biller.id,
            name=biller.name,
            code=biller.code,
            bill_type=biller.bill_type,
            category=biller.category,
            description=biller.description or "",
            logo_url=biller.logo_url,
            min_amount=float(biller.min_amount),
            max_amount=float(biller.max_amount),
            convenience_fee_type=biller.convenience_fee_type,
            convenience_fee_value=float(biller.convenience_fee_value),
            cashback_rate=float(biller.cashback_rate),
            processing_time_minutes=biller.processing_time_minutes,
            is_active=biller.is_active,
            supports_validation=biller.supports_validation,
            validation_pattern=biller.validation_pattern
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create biller"
        )

@router.put("/{biller_id}", response_model=BillerResponse)
async def update_biller(
    biller_id: int,
    biller_data: BillerUpdateRequest,
    current_admin = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_database_session)
):
    """Update biller (Admin only)."""
    try:
        # Get biller
        result = await db.execute(
            select(Biller).where(Biller.id == biller_id)
        )
        biller = result.scalar_one_or_none()
        
        if not biller:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Biller not found"
            )
        
        # Update fields
        update_data = biller_data.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(biller, field, value)
        
        biller.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(biller)
        
        return BillerResponse(
            id=biller.id,
            name=biller.name,
            code=biller.code,
            bill_type=biller.bill_type,
            category=biller.category,
            description=biller.description or "",
            logo_url=biller.logo_url,
            min_amount=float(biller.min_amount),
            max_amount=float(biller.max_amount),
            convenience_fee_type=biller.convenience_fee_type,
            convenience_fee_value=float(biller.convenience_fee_value),
            cashback_rate=float(biller.cashback_rate),
            processing_time_minutes=biller.processing_time_minutes,
            is_active=biller.is_active,
            supports_validation=biller.supports_validation,
            validation_pattern=biller.validation_pattern
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update biller"
        )