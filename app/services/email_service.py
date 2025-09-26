import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
import os
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from sqlalchemy.ext.asyncio import AsyncSession
from resend import Resend
from contextlib import asynccontextmanager

from app.core.config import settings
from app.models.email_log import EmailLog
from app.database import get_async_db

logger = logging.getLogger(__name__)

class EmailService:
    """Email service with Resend API configuration and template support."""
    
    def __init__(self):
        self.resend_client = Resend(api_key=settings.RESEND_API_KEY)
        self.from_email = settings.RESEND_FROM_EMAIL
        self.from_name = settings.RESEND_FROM_NAME
        
        # Setup Jinja2 environment for email templates
        template_dir = os.path.join(os.path.dirname(__file__), '..', 'templates', 'emails')
        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=True
        )
        
        logger.info(f"EmailService initialized with Resend API from: {self.from_email}")
    
    async def send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str = None,
        text_content: str = None,
        attachments: List[Dict[str, Any]] = None,
        db: AsyncSession = None
    ) -> bool:
        """Send email using Resend API with optional attachments and logging."""
        try:
            # Prepare email data
            email_data = {
                "from": f"{self.from_name} <{self.from_email}>",
                "to": [to_email],
                "subject": subject
            }
            
            # Add content
            if html_content:
                email_data["html"] = html_content
            if text_content:
                email_data["text"] = text_content
            
            # Add attachments if provided
            if attachments:
                email_data["attachments"] = [
                    {
                        "filename": attachment["filename"],
                        "content": attachment["content"]
                    }
                    for attachment in attachments
                ]
            
            # Send email using Resend
            response = self.resend_client.emails.send(email_data)
            
            # Log successful email
            if db:
                await self._log_email(
                    db=db,
                    to_email=to_email,
                    subject=subject,
                    status='sent',
                    html_content=html_content,
                    text_content=text_content,
                    resend_id=response.get('id')
                )
    
    async def _log_email(
        self,
        db: AsyncSession,
        to_email: str,
        subject: str,
        status: str,
        html_content: str = None,
        text_content: str = None,
        error_message: str = None,
        resend_id: str = None
    ):
        """Log email sending attempt to database."""
        try:
            email_log = EmailLog(
                to_email=to_email,
                subject=subject,
                html_content=html_content,
                text_content=text_content,
                status=status,
                error_message=error_message,
                resend_id=resend_id,
                sent_at=datetime.utcnow() if status == 'sent' else None,
                created_at=datetime.utcnow()
            )
            db.add(email_log)
            await db.commit()
            logger.info(f"Email log created for {to_email} with status: {status}")
        except Exception as e:
            logger.error(f"Failed to log email: {str(e)}")
    
    async def send_template_email(
        self,
        to_email: str,
        subject: str,
        template_name: str,
        template_data: Dict[str, Any],
        db: AsyncSession = None
    ) -> bool:
        """Send email using Jinja2 template."""
        try:
            # Render template
            html_content = await self._render_template(template_name, template_data)
            
            # Send email
            return await self.send_email(
                to_email=to_email,
                subject=subject,
                html_content=html_content,
                db=db
            )
        except Exception as e:
            logger.error(f"Failed to send template email: {str(e)}")
            return False
    
    async def _render_template(self, template_name: str, data: Dict[str, Any]) -> str:
        """Render Jinja2 template with provided data."""
        try:
            template = self.jinja_env.get_template(template_name)
            return template.render(**data)
        except Exception as e:
            logger.error(f"Failed to render template {template_name}: {str(e)}")
            raise
    
    async def send_verification_email(self, to_email: str, verification_token: str, db: AsyncSession = None) -> bool:
        """Send email verification email."""
        verification_url = f"{settings.FRONTEND_URL}/verify-email?token={verification_token}"
        
        template_data = {
            "verification_url": verification_url,
            "company_name": "Vision Fintech",
            "support_email": self.from_email
        }
        
        return await self.send_template_email(
            to_email=to_email,
            subject="Verify Your Email Address",
            template_name="welcome_verification.html",
            template_data=template_data,
            db=db
        )
    
    async def send_password_reset_email(self, to_email: str, reset_token: str, user_name: str = None, db: AsyncSession = None) -> bool:
        """Send password reset email."""
        reset_url = f"{settings.FRONTEND_URL}/reset-password?token={reset_token}"
        
        template_data = {
            "user_name": user_name or "User",
            "reset_url": reset_url,
            "company_name": "Vision Fintech",
            "support_email": self.from_email,
            "expiry_hours": 24,
            "help_center_url": f"{settings.FRONTEND_URL}/help",
            "support_phone": "1-800-VISION"
        }
        
        return await self.send_template_email(
            to_email=to_email,
            subject="Reset Your Password - Vision Fintech",
            template_name="password_reset.html",
            template_data=template_data,
            db=db
        )
    
    async def send_transaction_confirmation_email(
        self, 
        to_email: str, 
        transaction_data: Dict[str, Any], 
        user_name: str = None,
        db: AsyncSession = None
    ) -> bool:
        """Send transaction confirmation email."""
        try:
            template_data = {
                "user_name": user_name or "User",
                "transaction_id": transaction_data.get("transaction_id"),
                "amount": transaction_data.get("amount"),
                "currency": transaction_data.get("currency", "$"),
                "transaction_date": transaction_data.get("transaction_date", datetime.now().strftime("%B %d, %Y at %I:%M %p")),
                "merchant_name": transaction_data.get("merchant_name"),
                "payment_method": transaction_data.get("payment_method"),
                "transaction_type": transaction_data.get("transaction_type", "Payment"),
                "receipt_url": transaction_data.get("receipt_url"),
                "dashboard_url": f"{settings.FRONTEND_URL}/dashboard",
                "support_email": self.from_email,
                "company_name": "Vision Fintech"
            }
            
            return await self.send_template_email(
                to_email=to_email,
                subject=f"Transaction Confirmation - {template_data['transaction_id']}",
                template_name="transaction_confirmation.html",
                template_data=template_data,
                db=db
            )
        except Exception as e:
            logger.error(f"Failed to send transaction confirmation email: {str(e)}")
            return False
    
    async def send_payment_success_email(
        self, 
        to_email: str, 
        payment_data: Dict[str, Any], 
        user_name: str = None,
        db: AsyncSession = None
    ) -> bool:
        """Send payment success confirmation email."""
        try:
            template_data = {
                "user_name": user_name or "User",
                "payment_id": payment_data.get("payment_id"),
                "amount": payment_data.get("amount"),
                "currency": payment_data.get("currency", "$"),
                "payment_date": payment_data.get("payment_date", datetime.now().strftime("%B %d, %Y at %I:%M %p")),
                "merchant_name": payment_data.get("merchant_name"),
                "payment_method": payment_data.get("payment_method"),
                "confirmation_number": payment_data.get("confirmation_number"),
                "receipt_url": payment_data.get("receipt_url"),
                "bill_info": payment_data.get("bill_info"),
                "upcoming_bills": payment_data.get("upcoming_bills", []),
                "dashboard_url": f"{settings.FRONTEND_URL}/dashboard",
                "payment_history_url": f"{settings.FRONTEND_URL}/payments/history",
                "autopay_setup_url": f"{settings.FRONTEND_URL}/settings/autopay",
                "support_email": self.from_email,
                "feedback_url": f"{settings.FRONTEND_URL}/feedback",
                "company_name": "Vision Fintech"
            }
            
            return await self.send_template_email(
                to_email=to_email,
                subject="Payment Successful - Vision Fintech",
                template_name="payment_success.html",
                template_data=template_data,
                db=db
            )
        except Exception as e:
            logger.error(f"Failed to send payment success email: {str(e)}")
            return False
    
    async def send_payment_failure_email(
        self, 
        to_email: str, 
        payment_data: Dict[str, Any], 
        user_name: str = None,
        db: AsyncSession = None
    ) -> bool:
        """Send payment failure notification email."""
        try:
            template_data = {
                "user_name": user_name or "User",
                "payment_id": payment_data.get("payment_id"),
                "amount": payment_data.get("amount"),
                "currency": payment_data.get("currency", "$"),
                "failure_date": payment_data.get("failure_date", datetime.now().strftime("%B %d, %Y at %I:%M %p")),
                "merchant_name": payment_data.get("merchant_name"),
                "payment_method": payment_data.get("payment_method"),
                "failure_reason": payment_data.get("failure_reason", "Payment could not be processed"),
                "error_code": payment_data.get("error_code"),
                "retry_url": payment_data.get("retry_url"),
                "update_payment_url": f"{settings.FRONTEND_URL}/payment-methods",
                "dashboard_url": f"{settings.FRONTEND_URL}/dashboard",
                "support_email": self.from_email,
                "support_phone": "1-800-VISION",
                "live_chat_url": f"{settings.FRONTEND_URL}/support/chat",
                "company_name": "Vision Fintech"
            }
            
            return await self.send_template_email(
                to_email=to_email,
                subject="Payment Failed - Action Required",
                template_name="payment_failure.html",
                template_data=template_data,
                db=db
            )
        except Exception as e:
            logger.error(f"Failed to send payment failure email: {str(e)}")
            return False
    
    async def send_security_alert_email(
        self, 
        to_email: str, 
        alert_data: Dict[str, Any], 
        user_name: str = None,
        db: AsyncSession = None
    ) -> bool:
        """Send security alert notification email."""
        try:
            template_data = {
                "user_name": user_name or "User",
                "alert_type": alert_data.get("alert_type", "Security Alert"),
                "alert_date": alert_data.get("alert_date", datetime.now().strftime("%B %d, %Y at %I:%M %p")),
                "alert_description": alert_data.get("alert_description"),
                "ip_address": alert_data.get("ip_address"),
                "location": alert_data.get("location"),
                "device_info": alert_data.get("device_info"),
                "action_required": alert_data.get("action_required", False),
                "secure_account_url": f"{settings.FRONTEND_URL}/security/secure-account",
                "change_password_url": f"{settings.FRONTEND_URL}/change-password",
                "review_activity_url": f"{settings.FRONTEND_URL}/security/activity",
                "report_issue_url": f"{settings.FRONTEND_URL}/security/report",
                "dashboard_url": f"{settings.FRONTEND_URL}/dashboard",
                "support_email": self.from_email,
                "support_phone": "1-800-VISION",
                "emergency_contact": "security@visionfintech.com",
                "company_name": "Vision Fintech"
            }
            
            subject_prefix = " URGENT" if alert_data.get("action_required") else "🔒"
            
            return await self.send_template_email(
                to_email=to_email,
                subject=f"{subject_prefix} Security Alert - Vision Fintech",
                template_name="security_alert.html",
                template_data=template_data,
                db=db
            )
        except Exception as e:
            logger.error(f"Failed to send security alert email: {str(e)}")
            return False
    
    async def send_bill_reminder_email(
        self, 
        to_email: str, 
        reminder_data: Dict[str, Any], 
        user_name: str = None,
        db: AsyncSession = None
    ) -> bool:
        """Send bill payment reminder email."""
        try:
            bills = reminder_data.get("bills", [])
            bill_count = len(bills)
            total_amount = sum(float(bill.get("amount", 0)) for bill in bills)
            overdue_count = sum(1 for bill in bills if bill.get("is_overdue", False))
            urgent_count = sum(1 for bill in bills if bill.get("days_until_due", 999) <= 1 and not bill.get("is_overdue", False))
            potential_late_fees = sum(float(bill.get("late_fee", 0)) for bill in bills if bill.get("days_until_due", 999) <= 3)
            
            template_data = {
                "user_name": user_name or "User",
                "reminder_type": reminder_data.get("reminder_type"),
                "bills": bills,
                "bill_count": bill_count,
                "total_amount": f"{total_amount:.2f}",
                "currency": reminder_data.get("currency", "$"),
                "overdue_count": overdue_count if overdue_count > 0 else None,
                "urgent_count": urgent_count if urgent_count > 0 else None,
                "potential_late_fees": f"{potential_late_fees:.2f}" if potential_late_fees > 0 else None,
                "pay_bill_url": f"{settings.FRONTEND_URL}/pay-bill",
                "pay_all_url": f"{settings.FRONTEND_URL}/pay-all",
                "dashboard_url": f"{settings.FRONTEND_URL}/dashboard",
                "schedule_payments_url": f"{settings.FRONTEND_URL}/schedule-payments",
                "autopay_setup_url": f"{settings.FRONTEND_URL}/settings/autopay",
                "reminder_preferences_url": f"{settings.FRONTEND_URL}/settings/notifications",
                "payment_history_url": f"{settings.FRONTEND_URL}/payments/history",
                "on_time_percentage": reminder_data.get("on_time_percentage"),
                "total_payments": reminder_data.get("total_payments"),
                "total_paid": reminder_data.get("total_paid"),
                "support_email": self.from_email,
                "support_phone": "1-800-VISION",
                "live_chat_url": f"{settings.FRONTEND_URL}/support/chat",
                "help_center_url": f"{settings.FRONTEND_URL}/help",
                "unsubscribe_url": f"{settings.FRONTEND_URL}/unsubscribe",
                "company_name": "Vision Fintech"
            }
            
            # Determine subject based on urgency
            if overdue_count > 0:
                subject = f" URGENT: {overdue_count} Overdue Bill{'s' if overdue_count > 1 else ''} - Action Required"
            elif urgent_count > 0:
                subject = f" Bill{'s' if urgent_count > 1 else ''} Due Soon - Payment Reminder"
            else:
                subject = " Upcoming Bill Payment Reminder"
            
            return await self.send_template_email(
                to_email=to_email,
                subject=subject,
                template_name="bill_reminder.html",
                template_data=template_data,
                db=db
            )
        except Exception as e:
            logger.error(f"Failed to send bill reminder email: {str(e)}")
            return False


# Create global instance
email_service = EmailService()