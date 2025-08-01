#!/usr/bin/env python3
"""
Database seeding script for Vision Fintech Backend.

This script populates the database with initial data including:
- Sample billers
- Cashback rules
- Admin user
- Sample data for development
"""

import asyncio
import sys
import os
from decimal import Decimal
from datetime import datetime, timedelta

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import async_session_maker
from app.database_model.user import User
from app.database_model.wallet import Wallet
from app.database_model.biller import Biller, BillerStatus
from app.database_model.cashback import CashbackRule
from app.core.security import get_password_hash
from app.core.config import settings


async def create_admin_user(db: AsyncSession):
    """Create default admin user."""
    print("Creating admin user...")
    
    admin_email = "admin@visionfintech.com"
    
    # Check if admin already exists
    existing_admin = await db.execute(
        "SELECT * FROM users WHERE email = :email",
        {"email": admin_email}
    )
    if existing_admin.first():
        print("Admin user already exists")
        return
    
    admin_user = User(
        email=admin_email,
        phone="+2348000000000",
        password_hash=get_password_hash("AdminPassword123!"),
        first_name="System",
        last_name="Administrator",
        is_verified=True,
        is_admin=True,
        is_active=True,
        referral_code="ADMIN001",
        created_at=datetime.utcnow()
    )
    
    db.add(admin_user)
    await db.commit()
    await db.refresh(admin_user)
    
    # Create admin wallet
    admin_wallet = Wallet(
        user_id=admin_user.id,
        main_balance=Decimal('0.00'),
        cashback_balance=Decimal('0.00'),
        total_credited=Decimal('0.00'),
        total_debited=Decimal('0.00'),
        created_at=datetime.utcnow()
    )
    
    db.add(admin_wallet)
    await db.commit()
    
    print(f"Admin user created: {admin_email}")


async def create_sample_billers(db: AsyncSession):
    """Create sample billers for testing."""
    print("Creating sample billers...")
    
    billers_data = [
        {
            "name": "Ikeja Electric Power Authority",
            "code": "IKEJA_ELECTRIC",
            "bill_type": "electricity",
            "category": "utilities",
            "api_endpoint": "https://api.ikejaelectric.com",
            "api_key": "ikeja_api_key",
            "min_amount": 100.0,
            "max_amount": 50000.0,
            "fee_percentage": 1.5,
            "fee_cap": 200.0,
            "cashback_percentage": 1.0,
            "processing_time_minutes": 5,
            "validation_pattern": r"^\d{10,12}$",
            "is_active": True
        },
        {
            "name": "Eko Electricity Distribution",
            "code": "EKO_ELECTRIC",
            "bill_type": "electricity",
            "category": "utilities",
            "api_endpoint": "https://api.ekoelectricity.com",
            "api_key": "eko_api_key",
            "min_amount": 100.0,
            "max_amount": 50000.0,
            "fee_percentage": 1.5,
            "fee_cap": 200.0,
            "cashback_percentage": 1.0,
            "processing_time_minutes": 5,
            "validation_pattern": r"^\d{10,12}$",
            "is_active": True
        },
        {
            "name": "MTN Nigeria",
            "code": "MTN_AIRTIME",
            "bill_type": "airtime",
            "category": "telecommunications",
            "api_endpoint": "https://api.mtn.ng",
            "api_key": "mtn_api_key",
            "min_amount": 50.0,
            "max_amount": 10000.0,
            "fee_percentage": 0.5,
            "fee_cap": 50.0,
            "cashback_percentage": 0.5,
            "processing_time_minutes": 1,
            "validation_pattern": r"^(\+234|0)[789]\d{9}$",
            "is_active": True
        },
        {
            "name": "Airtel Nigeria",
            "code": "AIRTEL_AIRTIME",
            "bill_type": "airtime",
            "category": "telecommunications",
            "api_endpoint": "https://api.airtel.ng",
            "api_key": "airtel_api_key",
            "min_amount": 50.0,
            "max_amount": 10000.0,
            "fee_percentage": 0.5,
            "fee_cap": 50.0,
            "cashback_percentage": 0.5,
            "processing_time_minutes": 1,
            "validation_pattern": r"^(\+234|0)[789]\d{9}$",
            "is_active": True
        },
        {
            "name": "Spectranet Internet",
            "code": "SPECTRANET",
            "bill_type": "internet",
            "category": "telecommunications",
            "api_endpoint": "https://api.spectranet.com.ng",
            "api_key": "spectranet_api_key",
            "min_amount": 1000.0,
            "max_amount": 50000.0,
            "fee_percentage": 1.0,
            "fee_cap": 150.0,
            "cashback_percentage": 0.8,
            "processing_time_minutes": 10,
            "validation_pattern": r"^\d{8,12}$",
            "is_active": True
        },
        {
            "name": "DSTV",
            "code": "DSTV",
            "bill_type": "cable_tv",
            "category": "entertainment",
            "api_endpoint": "https://api.dstv.com",
            "api_key": "dstv_api_key",
            "min_amount": 1500.0,
            "max_amount": 25000.0,
            "fee_percentage": 1.0,
            "fee_cap": 100.0,
            "cashback_percentage": 0.5,
            "processing_time_minutes": 5,
            "validation_pattern": r"^\d{10}$",
            "is_active": True
        },
        {
            "name": "Lagos Water Corporation",
            "code": "LAGOS_WATER",
            "bill_type": "water",
            "category": "utilities",
            "api_endpoint": "https://api.lagoswater.gov.ng",
            "api_key": "lagos_water_api_key",
            "min_amount": 500.0,
            "max_amount": 20000.0,
            "fee_percentage": 1.5,
            "fee_cap": 100.0,
            "cashback_percentage": 1.0,
            "processing_time_minutes": 15,
            "validation_pattern": r"^\d{8,10}$",
            "is_active": True
        }
    ]
    
    for biller_data in billers_data:
        # Check if biller already exists
        existing_biller = await db.execute(
            "SELECT * FROM billers WHERE code = :code",
            {"code": biller_data["code"]}
        )
        if existing_biller.first():
            print(f"Biller {biller_data['code']} already exists")
            continue
        
        biller = Biller(**biller_data)
        db.add(biller)
        await db.commit()
        await db.refresh(biller)
        
        # Create biller status
        biller_status = BillerStatus(
            biller_id=biller.id,
            status="active",
            response_time_ms=150,
            success_rate=99.5,
            last_checked=datetime.utcnow()
        )
        db.add(biller_status)
        
        print(f"Created biller: {biller.name}")
    
    await db.commit()


async def create_cashback_rules(db: AsyncSession):
    """Create default cashback rules."""
    print("Creating cashback rules...")
    
    cashback_rules = [
        {
            "name": "Default Cashback",
            "description": "Default 1% cashback on all payments",
            "cashback_percentage": 1.0,
            "min_amount": 100.0,
            "max_amount": None,
            "max_cashback_per_transaction": 500.0,
            "max_cashback_per_month": 5000.0,
            "bill_type": None,
            "biller_code": None,
            "is_active": True,
            "priority": 1
        },
        {
            "name": "Electricity Bonus",
            "description": "Extra 0.5% cashback on electricity bills",
            "cashback_percentage": 1.5,
            "min_amount": 1000.0,
            "max_amount": None,
            "max_cashback_per_transaction": 750.0,
            "max_cashback_per_month": 7500.0,
            "bill_type": "electricity",
            "biller_code": None,
            "is_active": True,
            "priority": 2
        },
        {
            "name": "High Value Bonus",
            "description": "Extra cashback for payments above ₦10,000",
            "cashback_percentage": 2.0,
            "min_amount": 10000.0,
            "max_amount": None,
            "max_cashback_per_transaction": 1000.0,
            "max_cashback_per_month": 10000.0,
            "bill_type": None,
            "biller_code": None,
            "is_active": True,
            "priority": 3
        },
        {
            "name": "Weekend Special",
            "description": "Double cashback on weekends",
            "cashback_percentage": 2.0,
            "min_amount": 500.0,
            "max_amount": 5000.0,
            "max_cashback_per_transaction": 200.0,
            "max_cashback_per_month": 2000.0,
            "bill_type": None,
            "biller_code": None,
            "is_active": False,  # Can be activated for promotions
            "priority": 4
        }
    ]
    
    for rule_data in cashback_rules:
        # Check if rule already exists
        existing_rule = await db.execute(
            "SELECT * FROM cashback_rules WHERE name = :name",
            {"name": rule_data["name"]}
        )
        if existing_rule.first():
            print(f"Cashback rule '{rule_data['name']}' already exists")
            continue
        
        rule = CashbackRule(**rule_data)
        db.add(rule)
        print(f"Created cashback rule: {rule.name}")
    
    await db.commit()


async def create_sample_test_user(db: AsyncSession):
    """Create a sample test user for development."""
    print("Creating test user...")
    
    test_email = "test@example.com"
    
    # Check if test user already exists
    existing_user = await db.execute(
        "SELECT * FROM users WHERE email = :email",
        {"email": test_email}
    )
    if existing_user.first():
        print("Test user already exists")
        return
    
    test_user = User(
        email=test_email,
        phone="+2348012345678",
        password_hash=get_password_hash("TestPassword123!"),
        first_name="Test",
        last_name="User",
        is_verified=True,
        is_admin=False,
        is_active=True,
        referral_code="TEST001",
        created_at=datetime.utcnow()
    )
    
    db.add(test_user)
    await db.commit()
    await db.refresh(test_user)
    
    # Create test user wallet with some balance
    test_wallet = Wallet(
        user_id=test_user.id,
        main_balance=Decimal('10000.00'),
        cashback_balance=Decimal('500.00'),
        total_credited=Decimal('10500.00'),
        total_debited=Decimal('0.00'),
        created_at=datetime.utcnow()
    )
    
    db.add(test_wallet)
    await db.commit()
    
    print(f"Test user created: {test_email} (Password: TestPassword123!)")
    print(f"Test user wallet balance: ₦10,000.00 + ₦500.00 cashback")


async def main():
    """Main seeding function."""
    print("Starting database seeding...")
    print(f"Environment: {settings.environment}")
    print(f"Database URL: {settings.database_url}")
    
    async with async_session_maker() as db:
        try:
            await create_admin_user(db)
            await create_sample_billers(db)
            await create_cashback_rules(db)
            
            # Only create test user in development
            if settings.environment == "development":
                await create_sample_test_user(db)
            
            print("\n✅ Database seeding completed successfully!")
            print("\n📋 Summary:")
            print("   - Admin user created")
            print("   - Sample billers added")
            print("   - Cashback rules configured")
            if settings.environment == "development":
                print("   - Test user created")
            
            print("\n🚀 You can now start the application with: uvicorn app.main:app --reload")
            
        except Exception as e:
            print(f"❌ Error during seeding: {e}")
            await db.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(main())