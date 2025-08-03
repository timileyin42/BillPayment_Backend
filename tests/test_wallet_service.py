import pytest
import pytest_asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from app.services.wallet_service import WalletService
from app.database_model.wallet import Wallet, WalletTransaction
from app.core.errors import NotFoundError, InsufficientFundsError, ValidationError


@pytest.mark.unit
@pytest.mark.wallet
class TestWalletService:
    """Test suite for WalletService."""

    @pytest_asyncio.fixture
    async def wallet_service(self, db_session):
        """Create wallet service instance."""
        return WalletService(db_session)

    @pytest_asyncio.fixture
    async def test_wallet(self, db_session, test_user):
        """Create a test wallet."""
        wallet = Wallet(
            user_id=test_user.id,
            balance=1000.0,
            cashback_balance=100.0,
            total_funded=5000.0,
            total_spent=4000.0
        )
        db_session.add(wallet)
        await db_session.commit()
        await db_session.refresh(wallet)
        return wallet

    async def test_get_wallet_by_user_id_success(self, wallet_service, test_wallet):
        """Test getting wallet by user ID successfully."""
        wallet = await wallet_service.get_wallet_by_user_id(test_wallet.user_id)
        
        assert wallet is not None
        assert wallet.id == test_wallet.id
        assert wallet.user_id == test_wallet.user_id
        assert wallet.balance == 1000.0

    async def test_get_wallet_by_user_id_not_found(self, wallet_service):
        """Test getting wallet for non-existent user."""
        wallet = await wallet_service.get_wallet_by_user_id(99999)
        assert wallet is None

    async def test_create_wallet_success(self, wallet_service, test_user):
        """Test creating a new wallet successfully."""
        wallet = await wallet_service.create_wallet(test_user.id)
        
        assert wallet is not None
        assert wallet.user_id == test_user.id
        assert wallet.balance == 0.0
        assert wallet.cashback_balance == 0.0
        assert wallet.total_funded == 0.0
        assert wallet.total_spent == 0.0
        assert wallet.is_active is True

    async def test_create_wallet_already_exists(self, wallet_service, test_wallet):
        """Test creating wallet when one already exists."""
        existing_wallet = await wallet_service.create_wallet(test_wallet.user_id)
        
        assert existing_wallet.id == test_wallet.id
        assert existing_wallet.user_id == test_wallet.user_id

    async def test_get_balance_success(self, wallet_service, test_wallet):
        """Test getting wallet balance successfully."""
        balance_info = await wallet_service.get_balance(test_wallet.user_id)
        
        assert balance_info["balance"] == 1000.0
        assert balance_info["cashback_balance"] == 100.0
        assert balance_info["total_balance"] == 1100.0
        assert balance_info["total_funded"] == 5000.0
        assert balance_info["total_spent"] == 4000.0

    async def test_get_balance_wallet_not_found(self, wallet_service):
        """Test getting balance for non-existent wallet."""
        with pytest.raises(NotFoundError, match="Wallet not found"):
            await wallet_service.get_balance(99999)

    async def test_fund_wallet_success(self, wallet_service, test_user):
        """Test funding wallet successfully."""
        transaction = await wallet_service.fund_wallet(
            user_id=test_user.id,
            amount=500.0,
            payment_method="card",
            external_reference="ext_ref_123",
            description="Test funding"
        )
        
        assert transaction is not None
        assert transaction.transaction_type == "credit"
        assert transaction.amount == 500.0
        assert transaction.payment_method == "card"
        assert transaction.external_reference == "ext_ref_123"
        assert transaction.status == "pending"
        assert "FUND_" in transaction.reference

    async def test_fund_wallet_invalid_amount(self, wallet_service, test_user):
        """Test funding wallet with invalid amount."""
        with pytest.raises(ValidationError, match="Amount must be greater than zero"):
            await wallet_service.fund_wallet(
                user_id=test_user.id,
                amount=0.0,
                payment_method="card"
            )

        with pytest.raises(ValidationError, match="Amount must be greater than zero"):
            await wallet_service.fund_wallet(
                user_id=test_user.id,
                amount=-100.0,
                payment_method="card"
            )

    async def test_confirm_funding_success(self, wallet_service, test_wallet, db_session):
        """Test confirming funding transaction successfully."""
        # Create a pending funding transaction
        transaction = WalletTransaction(
            wallet_id=test_wallet.id,
            transaction_type="credit",
            amount=500.0,
            description="Test funding",
            reference="FUND_TEST123",
            payment_method="card",
            status="pending"
        )
        db_session.add(transaction)
        await db_session.commit()
        await db_session.refresh(transaction)
        
        # Confirm the funding
        confirmed_transaction = await wallet_service.confirm_funding(
            transaction.id, "ext_ref_456"
        )
        
        assert confirmed_transaction.status == "completed"
        assert confirmed_transaction.external_reference == "ext_ref_456"
        
        # Check wallet balance updated
        updated_wallet = await wallet_service.get_wallet_by_user_id(test_wallet.user_id)
        assert updated_wallet.balance == 1500.0  # 1000 + 500
        assert updated_wallet.total_funded == 5500.0  # 5000 + 500

    async def test_confirm_funding_transaction_not_found(self, wallet_service):
        """Test confirming non-existent funding transaction."""
        with pytest.raises(NotFoundError, match="Transaction not found"):
            await wallet_service.confirm_funding(99999)

    async def test_confirm_funding_already_completed(self, wallet_service, test_wallet, db_session):
        """Test confirming already completed funding transaction."""
        # Create a completed funding transaction
        transaction = WalletTransaction(
            wallet_id=test_wallet.id,
            transaction_type="credit",
            amount=500.0,
            description="Test funding",
            reference="FUND_TEST123",
            payment_method="card",
            status="completed"
        )
        db_session.add(transaction)
        await db_session.commit()
        await db_session.refresh(transaction)
        
        with pytest.raises(ValidationError, match="Transaction already completed"):
            await wallet_service.confirm_funding(transaction.id)

    async def test_debit_wallet_success(self, wallet_service, test_wallet):
        """Test debiting wallet successfully."""
        transaction = await wallet_service.debit_wallet(
            user_id=test_wallet.user_id,
            amount=300.0,
            description="Test payment",
            reference="PAY_TEST123"
        )
        
        assert transaction is not None
        assert transaction.transaction_type == "debit"
        assert transaction.amount == 300.0
        assert transaction.description == "Test payment"
        assert transaction.reference == "PAY_TEST123"
        assert transaction.status == "completed"
        
        # Check wallet balance updated
        updated_wallet = await wallet_service.get_wallet_by_user_id(test_wallet.user_id)
        assert updated_wallet.balance == 700.0  # 1000 - 300
        assert updated_wallet.total_spent == 4300.0  # 4000 + 300

    async def test_debit_wallet_with_cashback(self, wallet_service, test_wallet):
        """Test debiting wallet using cashback balance."""
        transaction = await wallet_service.debit_wallet(
            user_id=test_wallet.user_id,
            amount=1050.0,  # More than main balance, requires cashback
            description="Test payment with cashback",
            use_cashback=True
        )
        
        assert transaction.amount == 1050.0
        assert transaction.status == "completed"
        
        # Check wallet balances updated
        updated_wallet = await wallet_service.get_wallet_by_user_id(test_wallet.user_id)
        assert updated_wallet.balance == 0.0  # 1000 - 1000
        assert updated_wallet.cashback_balance == 50.0  # 100 - 50
        assert updated_wallet.total_spent == 5050.0  # 4000 + 1050

    async def test_debit_wallet_insufficient_funds(self, wallet_service, test_wallet):
        """Test debiting wallet with insufficient funds."""
        with pytest.raises(InsufficientFundsError):
            await wallet_service.debit_wallet(
                user_id=test_wallet.user_id,
                amount=1500.0,  # More than available balance
                description="Test payment"
            )

    async def test_debit_wallet_insufficient_funds_with_cashback(self, wallet_service, test_wallet):
        """Test debiting wallet with insufficient funds even with cashback."""
        with pytest.raises(InsufficientFundsError):
            await wallet_service.debit_wallet(
                user_id=test_wallet.user_id,
                amount=1200.0,  # More than total available (1000 + 100)
                description="Test payment",
                use_cashback=True
            )

    async def test_debit_wallet_invalid_amount(self, wallet_service, test_wallet):
        """Test debiting wallet with invalid amount."""
        with pytest.raises(ValidationError, match="Amount must be greater than zero"):
            await wallet_service.debit_wallet(
                user_id=test_wallet.user_id,
                amount=0.0,
                description="Test payment"
            )

    async def test_debit_wallet_not_found(self, wallet_service):
        """Test debiting non-existent wallet."""
        with pytest.raises(NotFoundError, match="Wallet not found"):
            await wallet_service.debit_wallet(
                user_id=99999,
                amount=100.0,
                description="Test payment"
            )

    async def test_add_cashback_success(self, wallet_service, test_wallet):
        """Test adding cashback successfully."""
        transaction = await wallet_service.add_cashback(
            user_id=test_wallet.user_id,
            amount=50.0,
            description="Cashback reward",
            reference="CASHBACK_TEST123"
        )
        
        assert transaction is not None
        assert transaction.transaction_type == "credit"
        assert transaction.amount == 50.0
        assert transaction.payment_method == "cashback"
        assert transaction.reference == "CASHBACK_TEST123"
        assert transaction.status == "completed"
        
        # Check cashback balance updated
        updated_wallet = await wallet_service.get_wallet_by_user_id(test_wallet.user_id)
        assert updated_wallet.cashback_balance == 150.0  # 100 + 50

    async def test_add_cashback_invalid_amount(self, wallet_service, test_wallet):
        """Test adding invalid cashback amount."""
        with pytest.raises(ValidationError, match="Cashback amount must be greater than zero"):
            await wallet_service.add_cashback(
                user_id=test_wallet.user_id,
                amount=0.0,
                description="Invalid cashback"
            )

    async def test_get_transaction_history_success(self, wallet_service, test_wallet, db_session):
        """Test getting transaction history successfully."""
        # Create some test transactions
        transactions = [
            WalletTransaction(
                wallet_id=test_wallet.id,
                transaction_type="credit",
                amount=100.0,
                description="Credit 1",
                reference="REF_001",
                status="completed"
            ),
            WalletTransaction(
                wallet_id=test_wallet.id,
                transaction_type="debit",
                amount=50.0,
                description="Debit 1",
                reference="REF_002",
                status="completed"
            ),
            WalletTransaction(
                wallet_id=test_wallet.id,
                transaction_type="credit",
                amount=200.0,
                description="Credit 2",
                reference="REF_003",
                status="completed"
            )
        ]
        
        for transaction in transactions:
            db_session.add(transaction)
        await db_session.commit()
        
        # Get all transactions
        history = await wallet_service.get_transaction_history(test_wallet.user_id)
        assert len(history) == 3
        
        # Get only credit transactions
        credit_history = await wallet_service.get_transaction_history(
            test_wallet.user_id, transaction_type="credit"
        )
        assert len(credit_history) == 2
        assert all(t.transaction_type == "credit" for t in credit_history)
        
        # Test pagination
        paginated_history = await wallet_service.get_transaction_history(
            test_wallet.user_id, limit=2, offset=1
        )
        assert len(paginated_history) == 2

    async def test_get_transaction_by_reference_success(self, wallet_service, test_wallet, db_session):
        """Test getting transaction by reference successfully."""
        transaction = WalletTransaction(
            wallet_id=test_wallet.id,
            transaction_type="credit",
            amount=100.0,
            description="Test transaction",
            reference="UNIQUE_REF_123",
            status="completed"
        )
        db_session.add(transaction)
        await db_session.commit()
        await db_session.refresh(transaction)
        
        found_transaction = await wallet_service.get_transaction_by_reference("UNIQUE_REF_123")
        assert found_transaction is not None
        assert found_transaction.id == transaction.id
        assert found_transaction.reference == "UNIQUE_REF_123"

    async def test_get_transaction_by_reference_not_found(self, wallet_service):
        """Test getting transaction by non-existent reference."""
        transaction = await wallet_service.get_transaction_by_reference("NON_EXISTENT_REF")
        assert transaction is None

    async def test_transfer_between_wallets_success(self, wallet_service, test_user, admin_user, db_session):
        """Test transferring funds between wallets successfully."""
        # Create wallets for both users
        sender_wallet = Wallet(
            user_id=test_user.id,
            balance=1000.0,
            cashback_balance=0.0,
            total_funded=1000.0,
            total_spent=0.0
        )
        receiver_wallet = Wallet(
            user_id=admin_user.id,
            balance=500.0,
            cashback_balance=0.0,
            total_funded=500.0,
            total_spent=0.0
        )
        
        db_session.add(sender_wallet)
        db_session.add(receiver_wallet)
        await db_session.commit()
        
        # Perform transfer
        result = await wallet_service.transfer_between_wallets(
            from_user_id=test_user.id,
            to_user_id=admin_user.id,
            amount=300.0,
            description="Test transfer"
        )
        
        assert "debit_transaction" in result
        assert "credit_transaction" in result
        
        debit_tx = result["debit_transaction"]
        credit_tx = result["credit_transaction"]
        
        assert debit_tx.transaction_type == "debit"
        assert debit_tx.amount == 300.0
        assert credit_tx.transaction_type == "credit"
        assert credit_tx.amount == 300.0
        
        # Check wallet balances
        sender_balance = await wallet_service.get_balance(test_user.id)
        receiver_balance = await wallet_service.get_balance(admin_user.id)
        
        assert sender_balance["balance"] == 700.0  # 1000 - 300
        assert receiver_balance["balance"] == 800.0  # 500 + 300

    async def test_transfer_between_wallets_same_user(self, wallet_service, test_user):
        """Test transferring to the same wallet (should fail)."""
        with pytest.raises(ValidationError, match="Cannot transfer to the same wallet"):
            await wallet_service.transfer_between_wallets(
                from_user_id=test_user.id,
                to_user_id=test_user.id,
                amount=100.0,
                description="Invalid transfer"
            )

    async def test_transfer_between_wallets_invalid_amount(self, wallet_service, test_user, admin_user):
        """Test transferring invalid amount."""
        with pytest.raises(ValidationError, match="Transfer amount must be greater than zero"):
            await wallet_service.transfer_between_wallets(
                from_user_id=test_user.id,
                to_user_id=admin_user.id,
                amount=0.0,
                description="Invalid transfer"
            )

    async def test_transfer_between_wallets_insufficient_funds(self, wallet_service, test_user, admin_user, db_session):
        """Test transferring with insufficient funds."""
        # Create sender wallet with low balance
        sender_wallet = Wallet(
            user_id=test_user.id,
            balance=100.0,
            cashback_balance=0.0,
            total_funded=100.0,
            total_spent=0.0
        )
        db_session.add(sender_wallet)
        await db_session.commit()
        
        with pytest.raises(InsufficientFundsError):
            await wallet_service.transfer_between_wallets(
                from_user_id=test_user.id,
                to_user_id=admin_user.id,
                amount=200.0,  # More than available
                description="Insufficient funds transfer"
            )