#!/usr/bin/env python3
"""
Test script for email templates and EmailService methods.
This script tests all email templates and service methods to ensure they work correctly.
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.email_service import EmailService
from app.core.config import settings


async def test_email_service():
    """Test all email service methods and templates."""
    print("🧪 Testing Email Service and Templates...\n")
    
    # Initialize email service
    email_service = EmailService()
    test_email = "test@example.com"
    
    print("📧 Email Service initialized successfully!")
    print(f"📬 Test email: {test_email}\n")
    
    # Test data for different email types
    test_data = {
        "verification": {
            "verification_token": "test_verification_token_123",
            "user_name": "John Doe"
        },
        "password_reset": {
            "reset_token": "test_reset_token_456",
            "user_name": "John Doe"
        },
        "transaction_confirmation": {
            "transaction_data": {
                "transaction_id": "TXN-2024-001",
                "amount": "150.00",
                "currency": "$",
                "transaction_date": datetime.now().strftime("%B %d, %Y at %I:%M %p"),
                "merchant_name": "Electric Company",
                "payment_method": "**** 1234",
                "transaction_type": "Bill Payment",
                "receipt_url": "https://example.com/receipt/TXN-2024-001"
            },
            "user_name": "John Doe"
        },
        "payment_success": {
            "payment_data": {
                "payment_id": "PAY-2024-001",
                "amount": "89.99",
                "currency": "$",
                "payment_date": datetime.now().strftime("%B %d, %Y at %I:%M %p"),
                "merchant_name": "Water Utility",
                "payment_method": "Visa **** 5678",
                "confirmation_number": "CONF-789123",
                "receipt_url": "https://example.com/receipt/PAY-2024-001",
                "bill_info": {
                    "bill_id": "BILL-2024-001",
                    "due_date": "2024-02-15",
                    "service_period": "January 2024"
                },
                "upcoming_bills": [
                    {"name": "Internet", "amount": "79.99", "due_date": "2024-02-20"},
                    {"name": "Phone", "amount": "45.00", "due_date": "2024-02-25"}
                ]
            },
            "user_name": "John Doe"
        },
        "payment_failure": {
            "payment_data": {
                "payment_id": "PAY-2024-002",
                "amount": "125.50",
                "currency": "$",
                "failure_date": datetime.now().strftime("%B %d, %Y at %I:%M %p"),
                "merchant_name": "Gas Company",
                "payment_method": "Mastercard **** 9012",
                "failure_reason": "Insufficient funds",
                "error_code": "ERR_INSUFFICIENT_FUNDS",
                "retry_url": "https://example.com/retry/PAY-2024-002"
            },
            "user_name": "John Doe"
        },
        "security_alert": {
            "alert_data": {
                "alert_type": "Suspicious Login Attempt",
                "alert_date": datetime.now().strftime("%B %d, %Y at %I:%M %p"),
                "alert_description": "We detected a login attempt from an unrecognized device.",
                "ip_address": "192.168.1.100",
                "location": "New York, NY, USA",
                "device_info": "Chrome on Windows 11",
                "action_required": True
            },
            "user_name": "John Doe"
        },
        "bill_reminder": {
            "reminder_data": {
                "reminder_type": "upcoming_bills",
                "bills": [
                    {
                        "name": "Electric Bill",
                        "amount": "145.67",
                        "due_date": "2024-02-15",
                        "days_until_due": 3,
                        "is_overdue": False,
                        "late_fee": "15.00",
                        "company": "City Electric",
                        "account_number": "****5678"
                    },
                    {
                        "name": "Water Bill",
                        "amount": "67.89",
                        "due_date": "2024-02-10",
                        "days_until_due": -2,
                        "is_overdue": True,
                        "late_fee": "10.00",
                        "company": "Metro Water",
                        "account_number": "****1234"
                    }
                ],
                "currency": "$",
                "on_time_percentage": 85,
                "total_payments": 24,
                "total_paid": "2,450.00"
            },
            "user_name": "John Doe"
        }
    }
    
    # Test each email template and method
    test_results = {}
    
    print("🔍 Testing Email Templates and Methods:\n")
    
    # Test 1: Welcome/Verification Email
    try:
        print("1️⃣ Testing Welcome/Verification Email...")
        result = await email_service.send_verification_email(
            to_email=test_email,
            verification_token=test_data["verification"]["verification_token"],
            user_name=test_data["verification"]["user_name"]
        )
        test_results["verification"] = "✅ PASS" if result else "❌ FAIL"
        print(f"   Result: {test_results['verification']}")
    except Exception as e:
        test_results["verification"] = f"❌ ERROR: {str(e)}"
        print(f"   Result: {test_results['verification']}")
    
    # Test 2: Password Reset Email
    try:
        print("\n2️⃣ Testing Password Reset Email...")
        result = await email_service.send_password_reset_email(
            to_email=test_email,
            reset_token=test_data["password_reset"]["reset_token"],
            user_name=test_data["password_reset"]["user_name"]
        )
        test_results["password_reset"] = "✅ PASS" if result else "❌ FAIL"
        print(f"   Result: {test_results['password_reset']}")
    except Exception as e:
        test_results["password_reset"] = f"❌ ERROR: {str(e)}"
        print(f"   Result: {test_results['password_reset']}")
    
    # Test 3: Transaction Confirmation Email
    try:
        print("\n3️⃣ Testing Transaction Confirmation Email...")
        result = await email_service.send_transaction_confirmation_email(
            to_email=test_email,
            transaction_data=test_data["transaction_confirmation"]["transaction_data"],
            user_name=test_data["transaction_confirmation"]["user_name"]
        )
        test_results["transaction_confirmation"] = "✅ PASS" if result else "❌ FAIL"
        print(f"   Result: {test_results['transaction_confirmation']}")
    except Exception as e:
        test_results["transaction_confirmation"] = f"❌ ERROR: {str(e)}"
        print(f"   Result: {test_results['transaction_confirmation']}")
    
    # Test 4: Payment Success Email
    try:
        print("\n4️⃣ Testing Payment Success Email...")
        result = await email_service.send_payment_success_email(
            to_email=test_email,
            payment_data=test_data["payment_success"]["payment_data"],
            user_name=test_data["payment_success"]["user_name"]
        )
        test_results["payment_success"] = "✅ PASS" if result else "❌ FAIL"
        print(f"   Result: {test_results['payment_success']}")
    except Exception as e:
        test_results["payment_success"] = f"❌ ERROR: {str(e)}"
        print(f"   Result: {test_results['payment_success']}")
    
    # Test 5: Payment Failure Email
    try:
        print("\n5️⃣ Testing Payment Failure Email...")
        result = await email_service.send_payment_failure_email(
            to_email=test_email,
            payment_data=test_data["payment_failure"]["payment_data"],
            user_name=test_data["payment_failure"]["user_name"]
        )
        test_results["payment_failure"] = "✅ PASS" if result else "❌ FAIL"
        print(f"   Result: {test_results['payment_failure']}")
    except Exception as e:
        test_results["payment_failure"] = f"❌ ERROR: {str(e)}"
        print(f"   Result: {test_results['payment_failure']}")
    
    # Test 6: Security Alert Email
    try:
        print("\n6️⃣ Testing Security Alert Email...")
        result = await email_service.send_security_alert_email(
            to_email=test_email,
            alert_data=test_data["security_alert"]["alert_data"],
            user_name=test_data["security_alert"]["user_name"]
        )
        test_results["security_alert"] = "✅ PASS" if result else "❌ FAIL"
        print(f"   Result: {test_results['security_alert']}")
    except Exception as e:
        test_results["security_alert"] = f"❌ ERROR: {str(e)}"
        print(f"   Result: {test_results['security_alert']}")
    
    # Test 7: Bill Reminder Email
    try:
        print("\n7️⃣ Testing Bill Reminder Email...")
        result = await email_service.send_bill_reminder_email(
            to_email=test_email,
            reminder_data=test_data["bill_reminder"]["reminder_data"],
            user_name=test_data["bill_reminder"]["user_name"]
        )
        test_results["bill_reminder"] = "✅ PASS" if result else "❌ FAIL"
        print(f"   Result: {test_results['bill_reminder']}")
    except Exception as e:
        test_results["bill_reminder"] = f"❌ ERROR: {str(e)}"
        print(f"   Result: {test_results['bill_reminder']}")
    
    # Print summary
    print("\n" + "="*60)
    print("📊 TEST SUMMARY")
    print("="*60)
    
    passed_count = sum(1 for result in test_results.values() if "✅ PASS" in result)
    total_count = len(test_results)
    
    for test_name, result in test_results.items():
        print(f"{test_name.replace('_', ' ').title():<30} {result}")
    
    print(f"\n📈 Overall Results: {passed_count}/{total_count} tests passed")
    
    if passed_count == total_count:
        print("🎉 All tests passed! Email service is working correctly.")
    else:
        print("⚠️  Some tests failed. Please check the errors above.")
    
    print("\n💡 Note: This test validates template rendering and method execution.")
    print("   Actual email sending requires valid Resend API configuration.")
    
    return test_results


async def test_template_rendering():
    """Test template rendering without sending emails."""
    print("\n🎨 Testing Template Rendering...\n")
    
    email_service = EmailService()
    templates_dir = Path("app/templates/emails")
    
    # Check if all template files exist
    required_templates = [
        "base.html",
        "welcome_verification.html",
        "password_reset.html",
        "transaction_confirmation.html",
        "payment_success.html",
        "payment_failure.html",
        "security_alert.html",
        "bill_reminder.html"
    ]
    
    print("📁 Checking template files:")
    for template in required_templates:
        template_path = templates_dir / template
        status = "✅ EXISTS" if template_path.exists() else "❌ MISSING"
        print(f"   {template:<30} {status}")
    
    # Test template rendering
    print("\n🔧 Testing template rendering:")
    
    test_context = {
        "user_name": "Test User",
        "company_name": "Vision Fintech",
        "support_email": "support@visionfintech.com"
    }
    
    for template in required_templates:
        if template == "base.html":  # Skip base template
            continue
            
        try:
            rendered = email_service.jinja_env.get_template(template).render(**test_context)
            status = "✅ RENDERS" if len(rendered) > 100 else "⚠️  SHORT"
            print(f"   {template:<30} {status}")
        except Exception as e:
            print(f"   {template:<30} ❌ ERROR: {str(e)[:50]}...")


if __name__ == "__main__":
    print("🚀 Starting Email Service Tests...\n")
    
    # Run template rendering tests
    asyncio.run(test_template_rendering())
    
    # Run email service tests
    asyncio.run(test_email_service())
    
    print("\n✨ Testing completed!")