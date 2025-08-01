from typing import Dict, List, Optional, Any, Union
from datetime import datetime
from pydantic import BaseModel, Field, validator
from decimal import Decimal

from app.database_model.cashback import CashbackStatus, CashbackRuleType, CashbackSourceType


class CashbackRuleBase(BaseModel):
    """Base model for cashback rules."""
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=1, max_length=500)
    rule_type: CashbackRuleType
    percentage: Decimal = Field(..., ge=0, le=100)
    min_transaction_amount: Decimal = Field(..., ge=0)
    max_cashback_amount: Optional[Decimal] = Field(None, ge=0)
    conditions: Dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    
    @validator('conditions')
    def validate_conditions(cls, v, values):
        """Validate that conditions match the rule type."""
        rule_type = values.get('rule_type')
        
        if rule_type == CashbackRuleType.BILL_TYPE:
            if 'bill_types' not in v or not isinstance(v['bill_types'], list) or not v['bill_types']:
                raise ValueError("BILL_TYPE rule must have 'bill_types' list in conditions")
        
        elif rule_type == CashbackRuleType.BILLER:
            if 'biller_codes' not in v or not isinstance(v['biller_codes'], list) or not v['biller_codes']:
                raise ValueError("BILLER rule must have 'biller_codes' list in conditions")
        
        elif rule_type == CashbackRuleType.FIRST_PAYMENT:
            # No specific conditions required for first payment
            pass
        
        elif rule_type == CashbackRuleType.PAYMENT_COUNT:
            if 'min_count' not in v or not isinstance(v['min_count'], int) or v['min_count'] <= 0:
                raise ValueError("PAYMENT_COUNT rule must have 'min_count' integer > 0 in conditions")
            if 'time_period_days' not in v or not isinstance(v['time_period_days'], int) or v['time_period_days'] <= 0:
                raise ValueError("PAYMENT_COUNT rule must have 'time_period_days' integer > 0 in conditions")
        
        elif rule_type == CashbackRuleType.PAYMENT_AMOUNT:
            if 'min_amount' not in v or not isinstance(v['min_amount'], (int, float, str)) or float(v['min_amount']) <= 0:
                raise ValueError("PAYMENT_AMOUNT rule must have 'min_amount' number > 0 in conditions")
            if 'time_period_days' not in v or not isinstance(v['time_period_days'], int) or v['time_period_days'] <= 0:
                raise ValueError("PAYMENT_AMOUNT rule must have 'time_period_days' integer > 0 in conditions")
        
        elif rule_type == CashbackRuleType.SPECIAL_PROMOTION:
            if 'promotion_code' not in v or not isinstance(v['promotion_code'], str) or not v['promotion_code']:
                raise ValueError("SPECIAL_PROMOTION rule must have 'promotion_code' string in conditions")
        
        return v
    
    @validator('end_date')
    def validate_end_date(cls, v, values):
        """Validate that end_date is after start_date if both are provided."""
        start_date = values.get('start_date')
        if v and start_date and v <= start_date:
            raise ValueError("end_date must be after start_date")
        return v


class CashbackRuleCreate(CashbackRuleBase):
    """Model for creating a new cashback rule."""
    pass


class CashbackRuleUpdate(BaseModel):
    """Model for updating an existing cashback rule."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, min_length=1, max_length=500)
    rule_type: Optional[CashbackRuleType] = None
    percentage: Optional[Decimal] = Field(None, ge=0, le=100)
    min_transaction_amount: Optional[Decimal] = Field(None, ge=0)
    max_cashback_amount: Optional[Decimal] = Field(None, ge=0)
    conditions: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    
    @validator('conditions')
    def validate_conditions(cls, v, values):
        """Validate that conditions match the rule type if both are provided."""
        if v is None:
            return v
            
        rule_type = values.get('rule_type')
        if rule_type is None:
            # Can't validate without knowing the rule type
            return v
            
        # Use the same validation logic as in CashbackRuleBase
        if rule_type == CashbackRuleType.BILL_TYPE:
            if 'bill_types' not in v or not isinstance(v['bill_types'], list) or not v['bill_types']:
                raise ValueError("BILL_TYPE rule must have 'bill_types' list in conditions")
        
        elif rule_type == CashbackRuleType.BILLER:
            if 'biller_codes' not in v or not isinstance(v['biller_codes'], list) or not v['biller_codes']:
                raise ValueError("BILLER rule must have 'biller_codes' list in conditions")
        
        elif rule_type == CashbackRuleType.FIRST_PAYMENT:
            # No specific conditions required for first payment
            pass
        
        elif rule_type == CashbackRuleType.PAYMENT_COUNT:
            if 'min_count' not in v or not isinstance(v['min_count'], int) or v['min_count'] <= 0:
                raise ValueError("PAYMENT_COUNT rule must have 'min_count' integer > 0 in conditions")
            if 'time_period_days' not in v or not isinstance(v['time_period_days'], int) or v['time_period_days'] <= 0:
                raise ValueError("PAYMENT_COUNT rule must have 'time_period_days' integer > 0 in conditions")
        
        elif rule_type == CashbackRuleType.PAYMENT_AMOUNT:
            if 'min_amount' not in v or not isinstance(v['min_amount'], (int, float, str)) or float(v['min_amount']) <= 0:
                raise ValueError("PAYMENT_AMOUNT rule must have 'min_amount' number > 0 in conditions")
            if 'time_period_days' not in v or not isinstance(v['time_period_days'], int) or v['time_period_days'] <= 0:
                raise ValueError("PAYMENT_AMOUNT rule must have 'time_period_days' integer > 0 in conditions")
        
        elif rule_type == CashbackRuleType.SPECIAL_PROMOTION:
            if 'promotion_code' not in v or not isinstance(v['promotion_code'], str) or not v['promotion_code']:
                raise ValueError("SPECIAL_PROMOTION rule must have 'promotion_code' string in conditions")
        
        return v
    
    @validator('end_date')
    def validate_end_date(cls, v, values):
        """Validate that end_date is after start_date if both are provided."""
        if v is None:
            return v
            
        start_date = values.get('start_date')
        if start_date is None:
            # Can't validate without knowing the start date
            return v
            
        if v <= start_date:
            raise ValueError("end_date must be after start_date")
        return v


class CashbackRuleResponse(CashbackRuleBase):
    """Model for cashback rule response."""
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        orm_mode = True


class CashbackBase(BaseModel):
    """Base model for cashback."""
    user_id: int
    amount: Decimal = Field(..., ge=0)
    source_type: CashbackSourceType
    source_id: Optional[int] = None
    rule_id: Optional[int] = None
    description: str
    status: CashbackStatus
    eligible_date: datetime
    credited_date: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    admin_notes: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class CashbackCreate(BaseModel):
    """Model for creating a new cashback."""
    user_id: int
    amount: Decimal = Field(..., ge=0)
    source_type: CashbackSourceType
    source_id: Optional[int] = None
    rule_id: Optional[int] = None
    description: str
    status: CashbackStatus = CashbackStatus.PENDING
    eligible_date: Optional[datetime] = None  # If not provided, will default to now
    metadata: Optional[Dict[str, Any]] = None


class CashbackResponse(CashbackBase):
    """Model for cashback response."""
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        orm_mode = True


class CashbackAdminUpdate(BaseModel):
    """Model for admin updates to cashback."""
    status: CashbackStatus
    admin_notes: Optional[str] = None
    rejection_reason: Optional[str] = None
    process_credit: bool = False  # Whether to process the credit to wallet if status is CREDITED


class CashbackUserResponse(BaseModel):
    """Model for cashback response to users."""
    id: int
    amount: Decimal
    description: str
    status: CashbackStatus
    eligible_date: datetime
    credited_date: Optional[datetime] = None
    created_at: datetime
    
    class Config:
        orm_mode = True


class CashbackStatistics(BaseModel):
    """Model for cashback statistics."""
    period: str
    from_date: Optional[datetime] = None
    to_date: datetime
    total_amount: float
    status_counts: Dict[str, int]
    status_amounts: Dict[str, float]
    top_users: List[Dict[str, Union[int, float]]]
    top_rules: List[Dict[str, Union[int, float, str]]]