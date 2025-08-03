import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from decimal import Decimal

from app.services.payment_service import PaymentService
from app.database_model.biller import Biller
from app.database_model.transaction import Transaction, RecurringPayment
from app.database_model.wallet import Wallet
from app.core.errors import (
    NotFoundError, ValidationError, PaymentFailedError,
    InsufficientFundsError, ExternalServiceError
)
from app.payment_model.abstract_biller import CustomerInfo


@pytest.mark.unit
@pytest.mark.payment
class TestPaymentService:
    """Test suite for PaymentService."""

    @pytest_asyncio.fixture
    async def payment_service(self, db_session):
        """Create payment service instance."""
        return PaymentService(db_session)

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

    async def test_get_biller_by_code_success(self, payment_service, test_biller):
        """Test getting biller by code successfully."""
        biller = await payment_service.get_biller_by_code("TEST_ELEC")
        
        assert biller is not None
        assert biller.id == test_biller.id
        assert biller.code == "TEST_ELEC"
        assert biller.name == "Test Electricity Company"

    async def test_get_biller_by_code_not_found(self, payment_service):
        """Test getting biller by non-existent code."""
        biller = await payment_service.get_biller_by_code("NON_EXISTENT")
        assert biller is None

    async def test_get_active_billers_all(self, payment_service, test_biller, db_session):
        """Test getting all active billers."""
        # Create another biller
        biller2 = Biller(
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
            is_active=True,
            is_featured=False
        )
        db_session.add(biller2)
        await db_session.commit()
        
        billers = await payment_service.get_active_billers()
        
        assert len(billers) >= 2
        assert any(b.code == "TEST_ELEC" for b in billers)
        assert any(b.code == "TEST_WATER" for b in billers)
        
        # Check ordering (featured first)
        featured_billers = [b for b in billers if b.is_featured]
        non_featured_billers = [b for b in billers if not b.is_featured]
        
        if featured_billers and non_featured_billers:
            assert billers.index(featured_billers[0]) < billers.index(non_featured_billers[0])

    async def test_get_active_billers_by_type(self, payment_service, test_biller, db_session):
        """Test getting active billers filtered by type."""
        # Create biller of different type
        biller2 = Biller(
            name="Test Airtime Provider",
            code="TEST_AIRTIME",
            bill_type="airtime",
            category="telecommunications",
            api_endpoint="https://api.testairtime.com",
            api_key="test_api_key",
            min_amount=50.0,
            max_amount=10000.0,
            transaction_fee=10.0,
            cashback_rate=1.0,
            processing_time_minutes=1,
            is_active=True
        )
        db_session.add(biller2)
        await db_session.commit()
        
        electricity_billers = await payment_service.get_active_billers("electricity")
        airtime_billers = await payment_service.get_active_billers("airtime")
        
        assert len(electricity_billers) >= 1
        assert len(airtime_billers) >= 1
        assert all(b.bill_type == "electricity" for b in electricity_billers)
        assert all(b.bill_type == "airtime" for b in airtime_billers)

    @patch('app.payment_model.provider_factory.BillerProviderFactory.create_biller')
    async def test_validate_customer_success(self, mock_create_biller, payment_service, test_biller):
        """Test customer validation success."""
        # Mock biller provider
        mock_provider = AsyncMock()
        mock_customer_info = CustomerInfo(
            customer_name="John Doe",
            customer_address="123 Test Street",
            account_status="active",
            outstanding_balance=0.0
        )
        mock_provider.validate_customer.return_value = mock_customer_info
        mock_create_biller.return_value = mock_provider
        
        customer_info = await payment_service.validate_customer("TEST_ELEC", "1234567890")
        
        assert customer_info.customer_name == "John Doe"
        assert customer_info.customer_address == "123 Test Street"
        assert customer_info.account_status == "active"
        mock_provider.validate_customer.assert_called_once_with("1234567890")

    async def test_validate_customer_biller_not_found(self, payment_service):
        """Test customer validation with non-existent biller."""
        with pytest.raises(NotFoundError, match="Biller not found: NON_EXISTENT"):
            await payment_service.validate_customer("NON_EXISTENT", "1234567890")

    async def test_validate_customer_biller_inactive(self, payment_service, test_biller, db_session):
        """Test customer validation with inactive biller."""
        # Deactivate biller
        test_biller.is_active = False
        await db_session.commit()
        
        with pytest.raises(ValidationError, match="Biller is currently unavailable"):
            await payment_service.validate_customer("TEST_ELEC", "1234567890")

    @patch('app.payment_model.provider_factory.BillerProviderFactory.create_biller')
    async def test_validate_customer_external_error(self, mock_create_biller, payment_service, test_biller):
        """Test customer validation with external service error."""
        mock_provider = AsyncMock()
        mock_provider.validate_customer.side_effect = Exception("External API error")
        mock_create_biller.return_value = mock_provider
        
        with pytest.raises(ExternalServiceError, match="Customer validation failed"):
            await payment_service.validate_customer("TEST_ELEC", "1234567890")

    @patch('app.services.cashback_service.CashbackService.calculate_cashback')
    async def test_calculate_payment_breakdown_success(self, mock_calculate_cashback, payment_service, test_biller, test_user):
        """Test payment breakdown calculation."""
        mock_calculate_cashback.return_value = 100.0
        
        breakdown = await payment_service.calculate_payment_breakdown(
            "TEST_ELEC", 5000.0, test_user.id
        )
        
        assert breakdown["bill_amount"] == 5000.0
        assert breakdown["transaction_fee"] == 50.0
        assert breakdown["total_amount"] == 5050.0
        assert breakdown["cashback_amount"] == 100.0
        assert breakdown["cashback_rate"] == 2.0
        assert breakdown["net_amount"] == 4950.0

    async def test_calculate_payment_breakdown_amount_too_low(self, payment_service, test_biller, test_user):
        """Test payment breakdown with amount below minimum."""
        with pytest.raises(ValidationError, match="Minimum amount is"):
            await payment_service.calculate_payment_breakdown(
                "TEST_ELEC", 50.0, test_user.id  # Below minimum of 100
            )

    async def test_calculate_payment_breakdown_amount_too_high(self, payment_service, test_biller, test_user):
        """Test payment breakdown with amount above maximum."""
        with pytest.raises(ValidationError, match="Maximum amount is"):
            await payment_service.calculate_payment_breakdown(
                "TEST_ELEC", 60000.0, test_user.id  # Above maximum of 50000
            )

    async def test_calculate_payment_breakdown_biller_not_found(self, payment_service, test_user):
        """Test payment breakdown with non-existent biller."""
        with pytest.raises(NotFoundError, match="Biller not found"):
            await payment_service.calculate_payment_breakdown(
                "NON_EXISTENT", 1000.0, test_user.id
            )

    @patch('app.services.payment_service.PaymentService._process_with_biller')
    @patch('app.services.cashback_service.CashbackService.calculate_cashback')
    async def test_process_payment_success(self, mock_calculate_cashback, mock_process_biller, 
                                         payment_service, test_biller, test_user, test_wallet):
        """Test successful payment processing."""
        mock_calculate_cashback.return_value = 100.0
        mock_process_biller.return_value = None
        
        transaction = await payment_service.process_payment(
            user_id=test_user.id,
            biller_code="TEST_ELEC",
            account_number="1234567890",
            amount=5000.0,
            customer_name="John Doe",
            phone_number="+2348012345678",
            email="john@example.com"
        )
        
        assert transaction is not None
        assert transaction.user_id == test_user.id
        assert transaction.biller_id == test_biller.id
        assert transaction.bill_amount == 5000.0
        assert transaction.transaction_fee == 50.0
        assert transaction.total_amount == 5050.0
        assert transaction.cashback_amount == 100.0
        assert transaction.account_number == "1234567890"
        assert transaction.customer_name == "John Doe"
        assert transaction.status == "processing"
        assert transaction.payment_status == "paid"
        assert "VIS_" in transaction.transaction_reference

    async def test_process_payment_biller_not_found(self, payment_service, test_user):
        """Test payment processing with non-existent biller."""
        with pytest.raises(NotFoundError, match="Biller not found"):
            await payment_service.process_payment(
                user_id=test_user.id,
                biller_code="NON_EXISTENT",
                account_number="1234567890",
                amount=5000.0
            )

    async def test_process_payment_biller_inactive(self, payment_service, test_biller, test_user, db_session):
        """Test payment processing with inactive biller."""
        test_biller.is_active = False
        await db_session.commit()
        
        with pytest.raises(ValidationError, match="Biller is currently unavailable"):
            await payment_service.process_payment(
                user_id=test_user.id,
                biller_code="TEST_ELEC",
                account_number="1234567890",
                amount=5000.0
            )

    @patch('app.services.cashback_service.CashbackService.calculate_cashback')
    async def test_process_payment_insufficient_funds(self, mock_calculate_cashback, payment_service, 
                                                    test_biller, test_user, test_wallet):
        """Test payment processing with insufficient funds."""
        mock_calculate_cashback.return_value = 100.0
        
        with pytest.raises(InsufficientFundsError):
            await payment_service.process_payment(
                user_id=test_user.id,
                biller_code="TEST_ELEC",
                account_number="1234567890",
                amount=15000.0  # More than available balance
            )

    @patch('app.services.payment_service.PaymentService._process_with_biller')
    @patch('app.services.cashback_service.CashbackService.calculate_cashback')
    async def test_process_payment_with_cashback(self, mock_calculate_cashback, mock_process_biller,
                                               payment_service, test_biller, test_user, test_wallet):
        """Test payment processing using cashback balance."""
        mock_calculate_cashback.return_value = 100.0
        mock_process_biller.return_value = None
        
        transaction = await payment_service.process_payment(
            user_id=test_user.id,
            biller_code="TEST_ELEC",
            account_number="1234567890",
            amount=10500.0,  # Requires using cashback
            use_cashback=True
        )
        
        assert transaction is not None
        assert transaction.total_amount == 10550.0  # 10500 + 50 fee
        assert transaction.status == "processing"

    async def test_get_transaction_by_reference_success(self, payment_service, test_biller, test_user, db_session):
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
        
        found_transaction = await payment_service.get_transaction_by_reference("VIS_TEST123")
        
        assert found_transaction is not None
        assert found_transaction.id == transaction.id
        assert found_transaction.transaction_reference == "VIS_TEST123"

    async def test_get_transaction_by_reference_not_found(self, payment_service):
        """Test getting transaction by non-existent reference."""
        transaction = await payment_service.get_transaction_by_reference("NON_EXISTENT")
        assert transaction is None

    async def test_get_user_transactions_success(self, payment_service, test_biller, test_user, db_session):
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
        
        user_transactions = await payment_service.get_user_transactions(test_user.id)
        
        assert len(user_transactions) >= 2
        assert any(t.transaction_reference == "VIS_TEST001" for t in user_transactions)
        assert any(t.transaction_reference == "VIS_TEST002" for t in user_transactions)

    async def test_get_user_transactions_with_filters(self, payment_service, test_biller, test_user, db_session):
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
        completed_transactions = await payment_service.get_user_transactions(
            test_user.id, status="completed"
        )
        pending_transactions = await payment_service.get_user_transactions(
            test_user.id, status="pending"
        )
        
        assert all(t.status == "completed" for t in completed_transactions)
        assert all(t.status == "pending" for t in pending_transactions)
        
        # Test bill type filter
        electricity_transactions = await payment_service.get_user_transactions(
            test_user.id, bill_type="electricity"
        )
        assert all(t.bill_type == "electricity" for t in electricity_transactions)

    async def test_get_user_transactions_pagination(self, payment_service, test_biller, test_user, db_session):
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
        page1 = await payment_service.get_user_transactions(
            test_user.id, limit=2, offset=0
        )
        page2 = await payment_service.get_user_transactions(
            test_user.id, limit=2, offset=2
        )
        
        assert len(page1) <= 2
        assert len(page2) <= 2
        
        # Ensure no overlap
        page1_refs = {t.transaction_reference for t in page1}
        page2_refs = {t.transaction_reference for t in page2}
        assert page1_refs.isdisjoint(page2_refs)

    async def test_create_recurring_payment_success(self, payment_service, test_biller, test_user, db_session):
        """Test creating recurring payment successfully."""
        from datetime import datetime, timedelta
        
        next_payment_date = datetime.utcnow() + timedelta(days=30)
        
        recurring_payment = await payment_service.create_recurring_payment(
            user_id=test_user.id,
            biller_code="TEST_ELEC",
            account_number="1234567890",
            amount=5000.0,
            frequency="monthly",
            next_payment_date=next_payment_date
        )
        
        assert recurring_payment is not None
        assert recurring_payment.user_id == test_user.id
        assert recurring_payment.biller_id == test_biller.id
        assert recurring_payment.account_number == "1234567890"
        assert recurring_payment.amount == 5000.0
        assert recurring_payment.frequency == "monthly"
        assert recurring_payment.is_active is True
        assert recurring_payment.auto_pay_enabled is True

    async def test_create_recurring_payment_biller_not_found(self, payment_service, test_user):
        """Test creating recurring payment with non-existent biller."""
        from datetime import datetime, timedelta
        
        next_payment_date = datetime.utcnow() + timedelta(days=30)
        
        with pytest.raises(NotFoundError, match="Biller not found"):
            await payment_service.create_recurring_payment(
                user_id=test_user.id,
                biller_code="NON_EXISTENT",
                account_number="1234567890",
                amount=5000.0,
                frequency="monthly",
                next_payment_date=next_payment_date
            )

    async def test_get_user_recurring_payments(self, payment_service, test_biller, test_user, db_session):
        """Test getting user recurring payments."""
        from datetime import datetime, timedelta
        
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
        
        # Get all recurring payments
        all_payments = await payment_service.get_user_recurring_payments(test_user.id)
        assert len(all_payments) >= 2
        
        # Get only active recurring payments
        active_payments = await payment_service.get_user_recurring_payments(
            test_user.id, active_only=True
        )
        assert all(rp.is_active for rp in active_payments)
        assert len(active_payments) >= 1

    async def test_update_transaction_status_success(self, payment_service, test_biller, test_user, db_session):
        """Test updating transaction status successfully."""
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
        
        updated_transaction = await payment_service.update_transaction_status(
            transaction.id, "completed", external_reference="EXT_REF_123"
        )
        
        assert updated_transaction.status == "completed"
        assert updated_transaction.external_reference == "EXT_REF_123"
        assert updated_transaction.completed_at is not None

    async def test_update_transaction_status_not_found(self, payment_service):
        """Test updating status of non-existent transaction."""
        with pytest.raises(NotFoundError, match="Transaction not found"):
            await payment_service.update_transaction_status(99999, "completed")

    async def test_refund_transaction_success(self, payment_service, test_biller, test_user, test_wallet, db_session):
        """Test refunding transaction successfully."""
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
        
        original_balance = test_wallet.balance
        
        refunded_transaction = await payment_service.refund_transaction(
            transaction.id, "Service unavailable"
        )
        
        assert refunded_transaction.status == "refunded"
        assert refunded_transaction.failure_reason == "Service unavailable"
        
        # Check wallet balance increased
        await db_session.refresh(test_wallet)
        assert test_wallet.balance == original_balance + 5050.0

    async def test_refund_transaction_not_found(self, payment_service):
        """Test refunding non-existent transaction."""
        with pytest.raises(NotFoundError, match="Transaction not found"):
            await payment_service.refund_transaction(99999, "Test refund")

    async def test_refund_transaction_invalid_status(self, payment_service, test_biller, test_user, db_session):
        """Test refunding transaction with invalid status."""
        transaction = Transaction(
            user_id=test_user.id,
            biller_id=test_biller.id,
            transaction_reference="VIS_TEST123",
            bill_type="electricity",
            bill_amount=5000.0,
            transaction_fee=50.0,
            total_amount=5050.0,
            account_number="1234567890",
            status="pending"  # Cannot refund pending transaction
        )
        db_session.add(transaction)
        await db_session.commit()
        await db_session.refresh(transaction)
        
        with pytest.raises(ValidationError, match="Cannot refund transaction"):
            await payment_service.refund_transaction(transaction.id, "Test refund")