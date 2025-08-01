import httpx
import asyncio
from typing import Dict, Any
from datetime import datetime
from .abstract_biller import AbstractBiller, CustomerInfo, PaymentRequest, PaymentResponse
from ..core.errors import ValidationError, PaymentFailedError, ExternalServiceError

class ElectricityBiller(AbstractBiller):
    """Electricity biller implementation for providers like IKEDC, EKEDC, etc."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.provider_code = config.get("provider_code", "IKEDC")
        self.service_type = config.get("service_type", "prepaid")  # prepaid or postpaid
    
    async def validate_customer(self, account_number: str) -> CustomerInfo:
        """Validate electricity meter number and get customer details."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                payload = {
                    "meter_number": account_number,
                    "service_type": self.service_type,
                    "provider_code": self.provider_code
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
                    raise ValidationError(f"Invalid meter number: {account_number}")
                
                if response.status_code != 200:
                    raise ExternalServiceError(f"Electricity service unavailable: {response.status_code}")
                
                data = response.json()
                
                if not data.get("success", False):
                    raise ValidationError(data.get("message", "Invalid meter number"))
                
                customer_data = data.get("data", {})
                
                return CustomerInfo(
                    account_number=account_number,
                    customer_name=customer_data.get("customer_name", "Unknown"),
                    address=customer_data.get("address"),
                    outstanding_balance=customer_data.get("outstanding_balance", 0.0),
                    account_status=customer_data.get("status", "active")
                )
                
        except httpx.TimeoutException:
            raise ExternalServiceError("Electricity service timeout")
        except httpx.RequestError as e:
            raise ExternalServiceError(f"Electricity service error: {str(e)}")
    
    async def process_payment(self, payment_request: PaymentRequest) -> PaymentResponse:
        """Process electricity bill payment."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                payload = {
                    "meter_number": payment_request.account_number,
                    "amount": payment_request.amount,
                    "service_type": self.service_type,
                    "provider_code": self.provider_code,
                    "reference": payment_request.reference,
                    "customer_name": payment_request.customer_name,
                    "phone_number": payment_request.phone_number
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
                    receipt_number=payment_data.get("receipt_number"),
                    units_purchased=payment_data.get("units"),
                    token=payment_data.get("token")  # For prepaid electricity
                )
                
        except httpx.TimeoutException:
            raise ExternalServiceError("Electricity payment service timeout")
        except httpx.RequestError as e:
            raise ExternalServiceError(f"Electricity payment service error: {str(e)}")
    
    async def check_transaction_status(self, reference: str) -> Dict[str, Any]:
        """Check electricity payment transaction status."""
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
    
    async def _make_health_check(self) -> bool:
        """Check if electricity service is healthy."""
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