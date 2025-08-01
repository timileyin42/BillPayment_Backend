import httpx
import asyncio
from typing import Dict, Any
from datetime import datetime
from .abstract_biller import AbstractBiller, CustomerInfo, PaymentRequest, PaymentResponse
from ..core.errors import ValidationError, PaymentFailedError, ExternalServiceError

class InternetBiller(AbstractBiller):
    """Internet/Cable TV biller implementation for providers like DSTV, GOtv, Spectranet, etc."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.provider_code = config.get("provider_code", "DSTV")
        self.service_category = config.get("service_category", "cable_tv")  # cable_tv, internet, data
    
    async def validate_customer(self, account_number: str) -> CustomerInfo:
        """Validate internet/cable account number and get customer details."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                payload = {
                    "account_number": account_number,
                    "provider_code": self.provider_code,
                    "service_category": self.service_category
                }
                
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
                
                response = await client.post(
                    f"{self.api_endpoint}/validate",
                    json=payload,
                    headers=headers
                )
                
                if response.status_code == 404:
                    raise ValidationError(f"Invalid account number: {account_number}")
                
                if response.status_code != 200:
                    raise ExternalServiceError(f"Internet service unavailable: {response.status_code}")
                
                data = response.json()
                
                if not data.get("success", False):
                    raise ValidationError(data.get("message", "Invalid account number"))
                
                customer_data = data.get("data", {})
                
                return CustomerInfo(
                    account_number=account_number,
                    customer_name=customer_data.get("customer_name", "Unknown"),
                    address=customer_data.get("address"),
                    outstanding_balance=customer_data.get("outstanding_balance", 0.0),
                    last_payment_date=self._parse_date(customer_data.get("last_payment_date")),
                    account_status=customer_data.get("status", "active")
                )
                
        except httpx.TimeoutException:
            raise ExternalServiceError("Internet service timeout")
        except httpx.RequestError as e:
            raise ExternalServiceError(f"Internet service error: {str(e)}")
    
    async def process_payment(self, payment_request: PaymentRequest) -> PaymentResponse:
        """Process internet/cable bill payment."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                payload = {
                    "account_number": payment_request.account_number,
                    "amount": payment_request.amount,
                    "provider_code": self.provider_code,
                    "service_category": self.service_category,
                    "reference": payment_request.reference,
                    "customer_name": payment_request.customer_name,
                    "phone_number": payment_request.phone_number,
                    "email": payment_request.email
                }
                
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
                
                response = await client.post(
                    f"{self.api_endpoint}/payment",
                    json=payload,
                    headers=headers
                )
                
                if response.status_code != 200:
                    raise PaymentFailedError(f"Payment failed: {response.status_code}")
                
                data = response.json()
                
                if not data.get("success", False):
                    raise PaymentFailedError(data.get("message", "Payment processing failed"))
                
                payment_data = data.get("data", {})
                
                return PaymentResponse(
                    success=True,
                    transaction_reference=payment_request.reference,
                    external_reference=payment_data.get("external_reference"),
                    message=payment_data.get("message", "Payment successful"),
                    receipt_number=payment_data.get("receipt_number")
                )
                
        except httpx.TimeoutException:
            raise ExternalServiceError("Internet payment service timeout")
        except httpx.RequestError as e:
            raise ExternalServiceError(f"Internet payment service error: {str(e)}")
    
    async def check_transaction_status(self, reference: str) -> Dict[str, Any]:
        """Check internet/cable payment transaction status."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
                
                response = await client.get(
                    f"{self.api_endpoint}/transaction/{reference}",
                    headers=headers
                )
                
                if response.status_code == 404:
                    return {
                        "status": "not_found",
                        "message": "Transaction not found"
                    }
                
                if response.status_code != 200:
                    return {
                        "status": "error",
                        "message": f"Status check failed: {response.status_code}"
                    }
                
                data = response.json()
                return data.get("data", {})
                
        except httpx.TimeoutException:
            return {
                "status": "timeout",
                "message": "Status check timeout"
            }
        except httpx.RequestError as e:
            return {
                "status": "error",
                "message": f"Status check error: {str(e)}"
            }
    
    async def get_available_packages(self) -> Dict[str, Any]:
        """Get available subscription packages for this provider."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
                
                response = await client.get(
                    f"{self.api_endpoint}/packages/{self.provider_code}",
                    headers=headers
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return data.get("data", {})
                
                return {"packages": []}
                
        except Exception:
            return {"packages": []}
    
    async def _make_health_check(self) -> bool:
        """Check if internet service is healthy."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
                
                response = await client.get(
                    f"{self.api_endpoint}/health",
                    headers=headers
                )
                
                return response.status_code == 200
                
        except Exception:
            return False
    
    def _parse_date(self, date_str: str) -> datetime:
        """Parse date string to datetime object."""
        if not date_str:
            return None
        
        try:
            # Try different date formats
            for fmt in ["%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y"]:
                try:
                    return datetime.strptime(date_str, fmt)
                except ValueError:
                    continue
            return None
        except Exception:
            return None