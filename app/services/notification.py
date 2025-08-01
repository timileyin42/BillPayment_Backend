import asyncio
import httpx
from typing import Optional, Dict, Any, List
from datetime import datetime
from ..core.config import settings
from ..core.errors import ExternalServiceError

class NotificationService:
    """Service for sending SMS and email notifications."""
    
    def __init__(self):
        self.sms_api_key = settings.sms_api_key
        self.email_api_key = settings.email_api_key
        self.timeout = 30
    
    async def send_sms(
        self,
        phone_number: str,
        message: str,
        reference: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send SMS notification."""
        if not self.sms_api_key:
            return {"success": False, "message": "SMS service not configured"}
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                payload = {
                    "to": phone_number,
                    "message": message,
                    "reference": reference or f"SMS_{datetime.utcnow().timestamp()}"
                }
                
                headers = {
                    "Authorization": f"Bearer {self.sms_api_key}",
                    "Content-Type": "application/json"
                }
                
                # Using a generic SMS API endpoint - replace with actual provider
                response = await client.post(
                    "https://api.sms-provider.com/send",
                    json=payload,
                    headers=headers
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return {
                        "success": True,
                        "message": "SMS sent successfully",
                        "reference": data.get("reference"),
                        "cost": data.get("cost", 0)
                    }
                else:
                    return {
                        "success": False,
                        "message": f"SMS sending failed: {response.status_code}"
                    }
                    
        except httpx.TimeoutException:
            return {
                "success": False,
                "message": "SMS service timeout"
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"SMS sending error: {str(e)}"
            }
    
    async def send_email(
        self,
        email: str,
        subject: str,
        message: str,
        html_content: Optional[str] = None,
        reference: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send email notification."""
        if not self.email_api_key:
            return {"success": False, "message": "Email service not configured"}
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                payload = {
                    "to": email,
                    "subject": subject,
                    "text": message,
                    "html": html_content,
                    "reference": reference or f"EMAIL_{datetime.utcnow().timestamp()}"
                }
                
                headers = {
                    "Authorization": f"Bearer {self.email_api_key}",
                    "Content-Type": "application/json"
                }
                
                # Using a generic email API endpoint - replace with actual provider
                response = await client.post(
                    "https://api.email-provider.com/send",
                    json=payload,
                    headers=headers
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return {
                        "success": True,
                        "message": "Email sent successfully",
                        "reference": data.get("reference")
                    }
                else:
                    return {
                        "success": False,
                        "message": f"Email sending failed: {response.status_code}"
                    }
                    
        except httpx.TimeoutException:
            return {
                "success": False,
                "message": "Email service timeout"
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Email sending error: {str(e)}"
            }
    
    async def send_payment_confirmation(
        self,
        phone_number: str,
        email: Optional[str],
        transaction_ref: str,
        amount: float,
        biller_name: str,
        account_number: str,
        cashback_amount: float = 0.0
    ) -> Dict[str, Any]:
        """Send payment confirmation notification."""
        # SMS message
        sms_message = (
            f"Payment Successful! "
            f"₦{amount:.2f} paid to {biller_name} ({account_number}). "
            f"Ref: {transaction_ref}"
        )
        
        if cashback_amount > 0:
            sms_message += f" Cashback: ₦{cashback_amount:.2f}"
        
        sms_message += " - Vision Fintech"
        
        # Send SMS
        sms_result = await self.send_sms(
            phone_number,
            sms_message,
            f"PAY_CONF_{transaction_ref}"
        )
        
        results = {"sms": sms_result}
        
        # Send email if provided
        if email:
            email_subject = f"Payment Confirmation - {transaction_ref}"
            email_message = (
                f"Dear Customer,\n\n"
                f"Your payment has been processed successfully.\n\n"
                f"Transaction Details:\n"
                f"- Amount: ₦{amount:.2f}\n"
                f"- Biller: {biller_name}\n"
                f"- Account: {account_number}\n"
                f"- Reference: {transaction_ref}\n"
            )
            
            if cashback_amount > 0:
                email_message += f"- Cashback Earned: ₦{cashback_amount:.2f}\n"
            
            email_message += (
                f"\nThank you for using Vision Fintech!\n\n"
                f"Best regards,\n"
                f"Vision Fintech Team"
            )
            
            email_result = await self.send_email(
                email,
                email_subject,
                email_message,
                reference=f"PAY_CONF_{transaction_ref}"
            )
            
            results["email"] = email_result
        
        return results
    
    async def send_wallet_funding_confirmation(
        self,
        phone_number: str,
        email: Optional[str],
        amount: float,
        payment_method: str,
        reference: str,
        new_balance: float
    ) -> Dict[str, Any]:
        """Send wallet funding confirmation."""
        # SMS message
        sms_message = (
            f"Wallet Funded! "
            f"₦{amount:.2f} added via {payment_method}. "
            f"New balance: ₦{new_balance:.2f}. "
            f"Ref: {reference} - Vision Fintech"
        )
        
        # Send SMS
        sms_result = await self.send_sms(
            phone_number,
            sms_message,
            f"FUND_CONF_{reference}"
        )
        
        results = {"sms": sms_result}
        
        # Send email if provided
        if email:
            email_subject = f"Wallet Funding Confirmation - {reference}"
            email_message = (
                f"Dear Customer,\n\n"
                f"Your wallet has been funded successfully.\n\n"
                f"Funding Details:\n"
                f"- Amount: ₦{amount:.2f}\n"
                f"- Payment Method: {payment_method}\n"
                f"- Reference: {reference}\n"
                f"- New Balance: ₦{new_balance:.2f}\n\n"
                f"Thank you for using Vision Fintech!\n\n"
                f"Best regards,\n"
                f"Vision Fintech Team"
            )
            
            email_result = await self.send_email(
                email,
                email_subject,
                email_message,
                reference=f"FUND_CONF_{reference}"
            )
            
            results["email"] = email_result
        
        return results
    
    async def send_cashback_notification(
        self,
        phone_number: str,
        email: Optional[str],
        cashback_amount: float,
        transaction_ref: str
    ) -> Dict[str, Any]:
        """Send cashback credit notification."""
        # SMS message
        sms_message = (
            f"Cashback Alert! "
            f"₦{cashback_amount:.2f} cashback credited to your wallet. "
            f"Ref: {transaction_ref} - Vision Fintech"
        )
        
        # Send SMS
        sms_result = await self.send_sms(
            phone_number,
            sms_message,
            f"CASHBACK_{transaction_ref}"
        )
        
        results = {"sms": sms_result}
        
        # Send email if provided
        if email:
            email_subject = f"Cashback Credited - {transaction_ref}"
            email_message = (
                f"Dear Customer,\n\n"
                f"Great news! You've earned cashback on your recent transaction.\n\n"
                f"Cashback Details:\n"
                f"- Amount: ₦{cashback_amount:.2f}\n"
                f"- Transaction Reference: {transaction_ref}\n\n"
                f"Your cashback has been credited to your wallet and is ready to use!\n\n"
                f"Keep paying bills with Vision Fintech to earn more rewards!\n\n"
                f"Best regards,\n"
                f"Vision Fintech Team"
            )
            
            email_result = await self.send_email(
                email,
                email_subject,
                email_message,
                reference=f"CASHBACK_{transaction_ref}"
            )
            
            results["email"] = email_result
        
        return results
    
    async def send_bulk_notifications(
        self,
        notifications: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Send multiple notifications concurrently."""
        tasks = []
        
        for notification in notifications:
            if notification["type"] == "sms":
                task = self.send_sms(
                    notification["phone_number"],
                    notification["message"],
                    notification.get("reference")
                )
            elif notification["type"] == "email":
                task = self.send_email(
                    notification["email"],
                    notification["subject"],
                    notification["message"],
                    notification.get("html_content"),
                    notification.get("reference")
                )
            else:
                continue
            
            tasks.append(task)
        
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            return [
                result if not isinstance(result, Exception) 
                else {"success": False, "message": str(result)}
                for result in results
            ]
        
        return []