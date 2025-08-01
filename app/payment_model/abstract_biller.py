from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from pydantic import BaseModel
from datetime import datetime

class CustomerInfo(BaseModel):
    """Customer information from biller validation."""
    account_number: str
    customer_name: str
    address: Optional[str] = None
    outstanding_balance: Optional[float] = None
    last_payment_date: Optional[datetime] = None
    account_status: str = "active"

class PaymentRequest(BaseModel):
    """Payment request data."""
    account_number: str
    amount: float
    customer_name: Optional[str] = None
    reference: str
    phone_number: Optional[str] = None
    email: Optional[str] = None

class PaymentResponse(BaseModel):
    """Payment response from biller."""
    success: bool
    transaction_reference: str
    external_reference: Optional[str] = None
    message: str
    receipt_number: Optional[str] = None
    units_purchased: Optional[float] = None  # For prepaid services
    token: Optional[str] = None  # For electricity tokens

class AbstractBiller(ABC):
    """Abstract base class for all biller implementations."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.name = config.get("name", "Unknown Biller")
        self.api_endpoint = config.get("api_endpoint")
        self.api_key = config.get("api_key")
        self.timeout = config.get("timeout", 30)
    
    @abstractmethod
    async def validate_customer(self, account_number: str) -> CustomerInfo:
        """Validate customer account and return customer information.
        
        Args:
            account_number: Customer's account/meter number
            
        Returns:
            CustomerInfo: Customer details if valid
            
        Raises:
            ValidationError: If account is invalid
            ExternalServiceError: If biller service is unavailable
        """
        pass
    
    @abstractmethod
    async def process_payment(self, payment_request: PaymentRequest) -> PaymentResponse:
        """Process payment to the biller.
        
        Args:
            payment_request: Payment details
            
        Returns:
            PaymentResponse: Payment result
            
        Raises:
            PaymentFailedError: If payment fails
            ExternalServiceError: If biller service is unavailable
        """
        pass
    
    @abstractmethod
    async def check_transaction_status(self, reference: str) -> Dict[str, Any]:
        """Check the status of a transaction.
        
        Args:
            reference: Transaction reference
            
        Returns:
            Dict containing transaction status information
        """
        pass
    
    async def get_service_status(self) -> Dict[str, Any]:
        """Check if the biller service is available.
        
        Returns:
            Dict containing service status information
        """
        try:
            # Default implementation - can be overridden
            response = await self._make_health_check()
            return {
                "status": "online" if response else "offline",
                "response_time": None,
                "last_checked": datetime.utcnow()
            }
        except Exception:
            return {
                "status": "offline",
                "response_time": None,
                "last_checked": datetime.utcnow()
            }
    
    async def _make_health_check(self) -> bool:
        """Make a health check request to the biller API.
        
        Returns:
            bool: True if service is healthy
        """
        # Default implementation - should be overridden by specific billers
        return True
    
    def get_fee_structure(self) -> Dict[str, float]:
        """Get the fee structure for this biller.
        
        Returns:
            Dict containing fee information
        """
        return {
            "transaction_fee": self.config.get("transaction_fee", 10.0),
            "min_amount": self.config.get("min_amount", 100.0),
            "max_amount": self.config.get("max_amount", 1000000.0)
        }