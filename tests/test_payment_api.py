import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from decimal import Decimal
from datetime import datetime, timedelta

from app.database_model.biller import Biller
from app.database_model.transaction import Transaction, RecurringPayment
from app.database_model.wallet import Wallet
from app.payment_model.abstract_biller import CustomerInfo


@pytest.mark.api
@pytest.mark.payment
class TestPaymentAPI:
    """Test suite for Payment API endpoints."""

    @pytest_asyncio.fixture
    async def test_biller(self, db_session):
        """Create a test biller."""
        biller = Biller(
            name="Test Electricity Company",
            code="TEST_ELEC",
            bill_type="electricity",
            category="utilities",
            api_endpoint="https://api.testelectric.com",
            api_key="test_api_key",
            min_amount=100.0,
            max_amount=50000.0,
            transaction_fee=50.0,
            cashback_rate=2.0,
            processing_time_minutes=5,
            is_active=True,
            is_featured=True
        )
        db_session.add(biller)
        await db_session.commit()
        await db_session.refresh(biller)
        return biller

    @pytest_asyncio.fixture
    async def test_wallet(self, db_session, test_user):
        """Create a test wallet with sufficient balance."""
        wallet = Wallet(
            user_id=test_user.id,
            balance=10000.0,
            cashback_balance=1000.0,
            total_funded=15000.0,
            total_spent=5000.0
        )
        db_session.add(wallet)
        await db_session.commit()
        await db_session.refresh(wallet)
        return wallet

    async def test_get_billers_success(self, test_client, test_biller):
        """Test getting all billers successfully."""
        response = await test_client.get("/api/v1/billers")
        
        assert response.status_code == 200
        data = response.json()
        assert "billers" in data
        assert len(data["billers"]) >= 1
        
        # Check biller structure
        biller = data["billers"][0]
        assert "id" in biller
        assert "name" in biller
        assert "code" in biller
        assert "bill_type" in biller
        assert "min_amount" in biller
        assert "max_amount" in biller
        assert "transaction_fee" in biller
        assert "cashback_rate" in biller

    async def test_get_billers_by_type(self, test_client, test_biller, db_session):
        """Test getting billers filtered by type."""
        # Create another biller of different type
        water_biller = Biller(
            name="Test Water Company",
            code="TEST_WATER",
            bill_type="water",
            category="utilities",
            api_endpoint="https://api.testwater.com",
            api_key="test_api_key",
            min_amount=50.0,
            max_amount=20000.0,
            transaction_fee=25.0,
            cashback_rate=1.5,
            processing_time_minutes=3,
            is_active=True
        )
        db_session.add(water_biller)
        await db_session.commit()
        
        # Test filtering by electricity
        response = await test_client.get("/api/v1/billers?bill_type=electricity")
        assert response.status_code == 200
        data = response.json()
        assert all(b["bill_type"] == "electricity" for b in data["billers"])
        
        # Test filtering by water
        response = await test_client.get("/api/v1/billers?bill_type=water")
        assert response.status_code == 200
        data = response.json()
        assert all(b["bill_type"] == "water" for b in data["billers"])

    async def test_get_biller_by_code_success(self, test_client, test_biller):
        """Test getting specific biller by code."""
        response = await test_client.get(f"/api/v1/billers/{test_biller.code}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == test_biller.code
        assert data["name"] == test_biller.name
        assert data["bill_type"] == test_biller.bill_type

    async def test_get_biller_by_code_not_found(self, test_client):
        """Test getting non-existent biller."""
        response = await test_client.get("/api/v1/billers/NON_EXISTENT")
        
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data

    @patch('app.services.payment_service.PaymentService.validate_customer')
    async def test_validate_customer_success(self, mock_validate, test_client, test_biller, test_auth_headers):
        """Test customer validation success."""
        mock_customer_info = CustomerInfo(
            customer_name="John Doe",
            customer_address="123 Test Street",
            account_status="active",
            outstanding_balance=0.0
        )
        mock_validate.return_value = mock_customer_info
        
        payload = {
            "biller_code": test_biller.code,
            "account_number": "1234567890"
        }
        
        response = await test_client.post(
            "/api/v1/payments/validate-customer",
            json=payload,
            headers=test_auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["customer_name"] == "John Doe"
        assert data["customer_address"] == "123 Test Street"
        assert data["account_status"] == "active"
        assert data["outstanding_balance"] == 0.0

    async def test_validate_customer_unauthorized(self, test_client, test_biller):
        """Test customer validation without authentication."""
        payload = {
            "biller_code": test_biller.code,
            "account_number": "1234567890"
        }
        
        response = await test_client.post(
            "/api/v1/payments/validate-customer",
            json=payload
        )
        
        assert response.status_code == 401

    async def test_validate_customer_missing_fields(self, test_client, test_auth_headers):
        """Test customer validation with missing required fields."""
        payload = {
            "biller_code": "TEST_ELEC"
            # Missing account_number
        }
        
        response = await test_client.post(
            "/api/v1/payments/validate-customer",
            json=payload,
            headers=test_auth_headers
        )
        
        assert response.status_code == 422

    @patch('app.services.payment_service.PaymentService.calculate_payment_breakdown')
    async def test_calculate_payment_breakdown_success(self, mock_calculate, test_client, test_biller, test_auth_headers):
        """Test payment breakdown calculation."""
        mock_breakdown = {
            "bill_amount": 5000.0,
            "transaction_fee": 50.0,
            "total_amount": 5050.0,
            "cashback_amount": 100.0,
            "cashback_rate": 2.0,
            "net_amount": 4950.0
        }
        mock_calculate.return_value = mock_breakdown
        
        payload = {
            "biller_code": test_biller.code,
            "amount": 5000.0
        }
        
        response = await test_client.post(
            "/api/v1/payments/calculate-breakdown",
            json=payload,
            headers=test_auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["bill_amount"] == 5000.0
        assert data["transaction_fee"] == 50.0
        assert data["total_amount"] == 5050.0
        assert data["cashback_amount"] == 100.0

    async def test_calculate_payment_breakdown_unauthorized(self, test_client, test_biller):
        """Test payment breakdown calculation without authentication."""
        payload = {
            "biller_code": test_biller.code,
            "amount": 5000.0
        }
        
        response = await test_client.post(
            "/api/v1/payments/calculate-breakdown",
            json=payload
        )
        
        assert response.status_code == 401

    @patch('app.services.payment_service.PaymentService.process_payment')
    async def test_process_payment_success(self, mock_process, test_client, test_biller, test_wallet, test_auth_headers):
        """Test successful payment processing."""
        mock_transaction = Transaction(
            id=1,
            user_id=test_wallet.user_id,
            biller_id=test_biller.id,
            transaction_reference="VIS_TEST123",
            bill_type="electricity",
            bill_amount=5000.0,
            transaction_fee=50.0,
            total_amount=5050.0,
            cashback_amount=100.0,
            account_number="1234567890",
            customer_name="John Doe",
            status="processing",
            payment_status="paid"
        )
        mock_process.return_value = mock_transaction
        
        payload = {
            "biller_code": test_biller.code,
            "account_number": "1234567890",
            "amount": 5000.0,
            "customer_name": "John Doe",
            "phone_number": "+2348012345678",
            "email": "john@example.com"
        }
        
        response = await test_client.post(
            "/api/v1/payments/process",
            json=payload,
            headers=test_auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["transaction_reference"] == "VIS_TEST123"
        assert data["status"] == "processing"
        assert data["bill_amount"] == 5000.0
        assert data["total_amount"] == 5050.0

    async def test_process_payment_unauthorized(self, test_client, test_biller):
        """Test payment processing without authentication."""
        payload = {
            "biller_code": test_biller.code,
            "account_number": "1234567890",
            "amount": 5000.0
        }
        
        response = await test_client.post(
            "/api/v1/payments/process",
            json=payload
        )
        
        assert response.status_code == 401

    async def test_process_payment_missing_fields(self, test_client, test_auth_headers):
        """Test payment processing with missing required fields."""
        payload = {
            "biller_code": "TEST_ELEC",
            "amount": 5000.0
            # Missing account_number
        }
        
        response = await test_client.post(
            "/api/v1/payments/process",
            json=payload,
            headers=test_auth_headers
        )
        
        assert response.status_code == 422

    async def test_process_payment_invalid_amount(self, test_client, test_biller, test_auth_headers):
        """Test payment processing with invalid amount."""
        payload = {
            "biller_code": test_biller.code,
            "account_number": "1234567890",
            "amount": -1000.0  # Negative amount
        }
        
        response = await test_client.post(
            "/api/v1/payments/process",
            json=payload,
            headers=test_auth_headers
        )
        
        assert response.status_code == 422

    async def test_get_transaction_by_reference_success(self, test_client, test_biller, test_user, test_auth_headers, db_session):
        """Test getting transaction by reference successfully."""
        transaction = Transaction(
            user_id=test_user.id,
            biller_id=test_biller.id,
            transaction_reference="VIS_TEST123",
            bill_type="electricity",
            bill_amount=5000.0,
            transaction_fee=50.0,
            total_amount=5050.0,
            account_number="1234567890",
            status="completed"
        )
        db_session.add(transaction)
        await db_session.commit()
        await db_session.refresh(transaction)
        
        response = await test_client.get(
            f"/api/v1/payments/transactions/{transaction.transaction_reference}",
            headers=test_auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["transaction_reference"] == "VIS_TEST123"
        assert data["bill_amount"] == 5000.0
        assert data["status"] == "completed"

    async def test_get_transaction_by_reference_not_found(self, test_client, test_auth_headers):
        """Test getting transaction by non-existent reference."""
        response = await test_client.get(
            "/api/v1/payments/transactions/NON_EXISTENT",
            headers=test_auth_headers
        )
        
        assert response.status_code == 404

    async def test_get_transaction_by_reference_unauthorized(self, test_client, test_biller, test_user, db_session):
        """Test getting transaction without authentication."""
        transaction = Transaction(
            user_id=test_user.id,
            biller_id=test_biller.id,
            transaction_reference="VIS_TEST123",
            bill_type="electricity",
            bill_amount=5000.0,
            transaction_fee=50.0,
            total_amount=5050.0,
            account_number="1234567890",
            status="completed"
        )
        db_session.add(transaction)
        await db_session.commit()
        
        response = await test_client.get(
            f"/api/v1/payments/transactions/{transaction.transaction_reference}"
        )
        
        assert response.status_code == 401

    async def test_get_user_transactions_success(self, test_client, test_biller, test_user, test_auth_headers, db_session):
        """Test getting user transactions successfully."""
        # Create test transactions
        transactions = [
            Transaction(
                user_id=test_user.id,
                biller_id=test_biller.id,
                transaction_reference="VIS_TEST001",
                bill_type="electricity",
                bill_amount=1000.0,
                transaction_fee=50.0,
                total_amount=1050.0,
                account_number="1234567890",
                status="completed"
            ),
            Transaction(
                user_id=test_user.id,
                biller_id=test_biller.id,
                transaction_reference="VIS_TEST002",
                bill_type="electricity",
                bill_amount=2000.0,
                transaction_fee=50.0,
                total_amount=2050.0,
                account_number="0987654321",
                status="pending"
            )
        ]
        
        for transaction in transactions:
            db_session.add(transaction)
        await db_session.commit()
        
        response = await test_client.get(
            "/api/v1/payments/transactions",
            headers=test_auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "transactions" in data
        assert len(data["transactions"]) >= 2

    async def test_get_user_transactions_with_filters(self, test_client, test_biller, test_user, test_auth_headers, db_session):
        """Test getting user transactions with filters."""
        # Create transactions with different statuses
        transactions = [
            Transaction(
                user_id=test_user.id,
                biller_id=test_biller.id,
                transaction_reference="VIS_COMPLETED",
                bill_type="electricity",
                bill_amount=1000.0,
                transaction_fee=50.0,
                total_amount=1050.0,
                account_number="1234567890",
                status="completed"
            ),
            Transaction(
                user_id=test_user.id,
                biller_id=test_biller.id,
                transaction_reference="VIS_PENDING",
                bill_type="electricity",
                bill_amount=2000.0,
                transaction_fee=50.0,
                total_amount=2050.0,
                account_number="0987654321",
                status="pending"
            )
        ]
        
        for transaction in transactions:
            db_session.add(transaction)
        await db_session.commit()
        
        # Test status filter
        response = await test_client.get(
            "/api/v1/payments/transactions?status=completed",
            headers=test_auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert all(t["status"] == "completed" for t in data["transactions"])
        
        # Test bill type filter
        response = await test_client.get(
            "/api/v1/payments/transactions?bill_type=electricity",
            headers=test_auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert all(t["bill_type"] == "electricity" for t in data["transactions"])

    async def test_get_user_transactions_pagination(self, test_client, test_biller, test_user, test_auth_headers, db_session):
        """Test user transactions pagination."""
        # Create multiple transactions
        transactions = []
        for i in range(5):
            transaction = Transaction(
                user_id=test_user.id,
                biller_id=test_biller.id,
                transaction_reference=f"VIS_TEST{i:03d}",
                bill_type="electricity",
                bill_amount=1000.0 * (i + 1),
                transaction_fee=50.0,
                total_amount=1000.0 * (i + 1) + 50.0,
                account_number="1234567890",
                status="completed"
            )
            transactions.append(transaction)
            db_session.add(transaction)
        
        await db_session.commit()
        
        # Test pagination
        response = await test_client.get(
            "/api/v1/payments/transactions?limit=2&offset=0",
            headers=test_auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["transactions"]) <= 2
        
        # Test second page
        response = await test_client.get(
            "/api/v1/payments/transactions?limit=2&offset=2",
            headers=test_auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["transactions"]) <= 2

    async def test_get_user_transactions_unauthorized(self, test_client):
        """Test getting user transactions without authentication."""
        response = await test_client.get("/api/v1/payments/transactions")
        
        assert response.status_code == 401

    @patch('app.services.payment_service.PaymentService.create_recurring_payment')
    async def test_create_recurring_payment_success(self, mock_create, test_client, test_biller, test_auth_headers):
        """Test creating recurring payment successfully."""
        next_payment_date = datetime.utcnow() + timedelta(days=30)
        
        mock_recurring_payment = RecurringPayment(
            id=1,
            user_id=1,
            biller_id=test_biller.id,
            bill_type="electricity",
            account_number="1234567890",
            amount=5000.0,
            frequency="monthly",
            next_payment_date=next_payment_date,
            is_active=True,
            auto_pay_enabled=True
        )
        mock_create.return_value = mock_recurring_payment
        
        payload = {
            "biller_code": test_biller.code,
            "account_number": "1234567890",
            "amount": 5000.0,
            "frequency": "monthly",
            "next_payment_date": next_payment_date.isoformat()
        }
        
        response = await test_client.post(
            "/api/v1/payments/recurring",
            json=payload,
            headers=test_auth_headers
        )
        
        assert response.status_code == 201
        data = response.json()
        assert data["account_number"] == "1234567890"
        assert data["amount"] == 5000.0
        assert data["frequency"] == "monthly"
        assert data["is_active"] is True

    async def test_create_recurring_payment_unauthorized(self, test_client, test_biller):
        """Test creating recurring payment without authentication."""
        next_payment_date = datetime.utcnow() + timedelta(days=30)
        
        payload = {
            "biller_code": test_biller.code,
            "account_number": "1234567890",
            "amount": 5000.0,
            "frequency": "monthly",
            "next_payment_date": next_payment_date.isoformat()
        }
        
        response = await test_client.post(
            "/api/v1/payments/recurring",
            json=payload
        )
        
        assert response.status_code == 401

    async def test_get_recurring_payments_success(self, test_client, test_biller, test_user, test_auth_headers, db_session):
        """Test getting user recurring payments successfully."""
        # Create recurring payments
        recurring_payments = [
            RecurringPayment(
                user_id=test_user.id,
                biller_id=test_biller.id,
                bill_type="electricity",
                account_number="1234567890",
                amount=5000.0,
                frequency="monthly",
                next_payment_date=datetime.utcnow() + timedelta(days=30),
                is_active=True
            ),
            RecurringPayment(
                user_id=test_user.id,
                biller_id=test_biller.id,
                bill_type="electricity",
                account_number="0987654321",
                amount=3000.0,
                frequency="weekly",
                next_payment_date=datetime.utcnow() + timedelta(days=7),
                is_active=False
            )
        ]
        
        for rp in recurring_payments:
            db_session.add(rp)
        await db_session.commit()
        
        response = await test_client.get(
            "/api/v1/payments/recurring",
            headers=test_auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "recurring_payments" in data
        assert len(data["recurring_payments"]) >= 2

    async def test_get_recurring_payments_active_only(self, test_client, test_biller, test_user, test_auth_headers, db_session):
        """Test getting only active recurring payments."""
        # Create recurring payments
        recurring_payments = [
            RecurringPayment(
                user_id=test_user.id,
                biller_id=test_biller.id,
                bill_type="electricity",
                account_number="1234567890",
                amount=5000.0,
                frequency="monthly",
                next_payment_date=datetime.utcnow() + timedelta(days=30),
                is_active=True
            ),
            RecurringPayment(
                user_id=test_user.id,
                biller_id=test_biller.id,
                bill_type="electricity",
                account_number="0987654321",
                amount=3000.0,
                frequency="weekly",
                next_payment_date=datetime.utcnow() + timedelta(days=7),
                is_active=False
            )
        ]
        
        for rp in recurring_payments:
            db_session.add(rp)
        await db_session.commit()
        
        response = await test_client.get(
            "/api/v1/payments/recurring?active_only=true",
            headers=test_auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert all(rp["is_active"] for rp in data["recurring_payments"])

    async def test_get_recurring_payments_unauthorized(self, test_client):
        """Test getting recurring payments without authentication."""
        response = await test_client.get("/api/v1/payments/recurring")
        
        assert response.status_code == 401

    @patch('app.services.payment_service.PaymentService.update_transaction_status')
    async def test_update_transaction_status_success(self, mock_update, test_client, test_biller, test_user, test_admin_auth_headers, db_session):
        """Test updating transaction status successfully (admin only)."""
        transaction = Transaction(
            user_id=test_user.id,
            biller_id=test_biller.id,
            transaction_reference="VIS_TEST123",
            bill_type="electricity",
            bill_amount=5000.0,
            transaction_fee=50.0,
            total_amount=5050.0,
            account_number="1234567890",
            status="processing"
        )
        db_session.add(transaction)
        await db_session.commit()
        await db_session.refresh(transaction)
        
        transaction.status = "completed"
        mock_update.return_value = transaction
        
        payload = {
            "status": "completed",
            "external_reference": "EXT_REF_123"
        }
        
        response = await test_client.patch(
            f"/api/v1/payments/transactions/{transaction.id}/status",
            json=payload,
            headers=test_admin_auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"

    async def test_update_transaction_status_unauthorized(self, test_client, test_auth_headers):
        """Test updating transaction status without admin privileges."""
        payload = {
            "status": "completed"
        }
        
        response = await test_client.patch(
            "/api/v1/payments/transactions/1/status",
            json=payload,
            headers=test_auth_headers  # Regular user, not admin
        )
        
        assert response.status_code == 403

    @patch('app.services.payment_service.PaymentService.refund_transaction')
    async def test_refund_transaction_success(self, mock_refund, test_client, test_biller, test_user, test_admin_auth_headers, db_session):
        """Test refunding transaction successfully (admin only)."""
        transaction = Transaction(
            user_id=test_user.id,
            biller_id=test_biller.id,
            transaction_reference="VIS_TEST123",
            bill_type="electricity",
            bill_amount=5000.0,
            transaction_fee=50.0,
            total_amount=5050.0,
            account_number="1234567890",
            status="completed"
        )
        db_session.add(transaction)
        await db_session.commit()
        await db_session.refresh(transaction)
        
        transaction.status = "refunded"
        mock_refund.return_value = transaction
        
        payload = {
            "reason": "Service unavailable"
        }
        
        response = await test_client.post(
            f"/api/v1/payments/transactions/{transaction.id}/refund",
            json=payload,
            headers=test_admin_auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "refunded"

    async def test_refund_transaction_unauthorized(self, test_client, test_auth_headers):
        """Test refunding transaction without admin privileges."""
        payload = {
            "reason": "Test refund"
        }
        
        response = await test_client.post(
            "/api/v1/payments/transactions/1/refund",
            json=payload,
            headers=test_auth_headers  # Regular user, not admin
        )
        
        assert response.status_code == 403