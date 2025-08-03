import pytest
import pytest_asyncio
from httpx import AsyncClient
from unittest.mock import patch, AsyncMock

from app.database_model.wallet import Wallet, WalletTransaction
from app.services.wallet_service import WalletService


@pytest.mark.api
@pytest.mark.wallet
class TestWalletAPI:
    """Test suite for Wallet API endpoints."""

    @pytest_asyncio.fixture
    async def test_wallet(self, db_session, test_user):
        """Create a test wallet with balance."""
        wallet = Wallet(
            user_id=test_user.id,
            balance=5000.0,
            cashback_balance=500.0,
            total_funded=10000.0,
            total_spent=5000.0
        )
        db_session.add(wallet)
        await db_session.commit()
        await db_session.refresh(wallet)
        return wallet

    async def test_get_wallet_balance_success(self, client: AsyncClient, auth_headers, test_wallet):
        """Test getting wallet balance successfully."""
        response = await client.get("/api/v1/wallet/balance", headers=auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["balance"] == 5000.0
        assert data["cashback_balance"] == 500.0
        assert data["total_balance"] == 5500.0
        assert data["total_funded"] == 10000.0
        assert data["total_spent"] == 5000.0

    async def test_get_wallet_balance_unauthorized(self, client: AsyncClient):
        """Test getting wallet balance without authentication."""
        response = await client.get("/api/v1/wallet/balance")
        assert response.status_code == 401

    async def test_get_wallet_balance_no_wallet(self, client: AsyncClient, auth_headers):
        """Test getting balance when wallet doesn't exist."""
        response = await client.get("/api/v1/wallet/balance", headers=auth_headers)
        
        # Should create wallet automatically or return 404
        assert response.status_code in [200, 404]
        
        if response.status_code == 200:
            data = response.json()
            assert data["balance"] == 0.0
            assert data["cashback_balance"] == 0.0

    async def test_fund_wallet_success(self, client: AsyncClient, auth_headers, sample_wallet_funding_data):
        """Test funding wallet successfully."""
        with patch('app.services.wallet_service.WalletService.fund_wallet') as mock_fund:
            mock_transaction = AsyncMock()
            mock_transaction.id = 1
            mock_transaction.reference = "FUND_TEST123"
            mock_transaction.amount = 10000.0
            mock_transaction.status = "pending"
            mock_transaction.payment_method = "paystack"
            mock_fund.return_value = mock_transaction
            
            response = await client.post(
                "/api/v1/wallet/fund",
                json=sample_wallet_funding_data,
                headers=auth_headers
            )
            
            assert response.status_code == 200
            data = response.json()
            
            assert data["reference"] == "FUND_TEST123"
            assert data["amount"] == 10000.0
            assert data["status"] == "pending"
            assert data["payment_method"] == "paystack"

    async def test_fund_wallet_invalid_amount(self, client: AsyncClient, auth_headers):
        """Test funding wallet with invalid amount."""
        invalid_data = {
            "amount": 50.0,  # Below minimum
            "payment_method": "card"
        }
        
        response = await client.post(
            "/api/v1/wallet/fund",
            json=invalid_data,
            headers=auth_headers
        )
        
        assert response.status_code == 422  # Validation error

    async def test_fund_wallet_invalid_payment_method(self, client: AsyncClient, auth_headers):
        """Test funding wallet with invalid payment method."""
        invalid_data = {
            "amount": 1000.0,
            "payment_method": "invalid_method"
        }
        
        response = await client.post(
            "/api/v1/wallet/fund",
            json=invalid_data,
            headers=auth_headers
        )
        
        assert response.status_code == 422  # Validation error

    async def test_fund_wallet_missing_fields(self, client: AsyncClient, auth_headers):
        """Test funding wallet with missing required fields."""
        invalid_data = {
            "amount": 1000.0
            # Missing payment_method
        }
        
        response = await client.post(
            "/api/v1/wallet/fund",
            json=invalid_data,
            headers=auth_headers
        )
        
        assert response.status_code == 422  # Validation error

    async def test_confirm_funding_success(self, client: AsyncClient, auth_headers, test_wallet, db_session):
        """Test confirming funding transaction successfully."""
        # Create a pending funding transaction
        transaction = WalletTransaction(
            wallet_id=test_wallet.id,
            transaction_type="credit",
            amount=1000.0,
            description="Test funding",
            reference="FUND_TEST123",
            payment_method="card",
            status="pending"
        )
        db_session.add(transaction)
        await db_session.commit()
        await db_session.refresh(transaction)
        
        confirm_data = {
            "transaction_id": transaction.id,
            "external_reference": "ext_ref_456"
        }
        
        response = await client.post(
            "/api/v1/wallet/confirm-funding",
            json=confirm_data,
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "completed"
        assert data["external_reference"] == "ext_ref_456"

    async def test_confirm_funding_transaction_not_found(self, client: AsyncClient, auth_headers):
        """Test confirming non-existent funding transaction."""
        confirm_data = {
            "transaction_id": 99999,
            "external_reference": "ext_ref_456"
        }
        
        response = await client.post(
            "/api/v1/wallet/confirm-funding",
            json=confirm_data,
            headers=auth_headers
        )
        
        assert response.status_code == 404

    async def test_get_transaction_history_success(self, client: AsyncClient, auth_headers, test_wallet, db_session):
        """Test getting transaction history successfully."""
        # Create some test transactions
        transactions = [
            WalletTransaction(
                wallet_id=test_wallet.id,
                transaction_type="credit",
                amount=1000.0,
                description="Funding",
                reference="REF_001",
                status="completed"
            ),
            WalletTransaction(
                wallet_id=test_wallet.id,
                transaction_type="debit",
                amount=500.0,
                description="Payment",
                reference="REF_002",
                status="completed"
            )
        ]
        
        for transaction in transactions:
            db_session.add(transaction)
        await db_session.commit()
        
        response = await client.get("/api/v1/wallet/transactions", headers=auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert len(data) >= 2
        assert any(t["reference"] == "REF_001" for t in data)
        assert any(t["reference"] == "REF_002" for t in data)

    async def test_get_transaction_history_with_filters(self, client: AsyncClient, auth_headers, test_wallet, db_session):
        """Test getting transaction history with filters."""
        # Create test transactions
        transactions = [
            WalletTransaction(
                wallet_id=test_wallet.id,
                transaction_type="credit",
                amount=1000.0,
                description="Funding",
                reference="REF_001",
                status="completed"
            ),
            WalletTransaction(
                wallet_id=test_wallet.id,
                transaction_type="debit",
                amount=500.0,
                description="Payment",
                reference="REF_002",
                status="completed"
            )
        ]
        
        for transaction in transactions:
            db_session.add(transaction)
        await db_session.commit()
        
        # Test filtering by transaction type
        response = await client.get(
            "/api/v1/wallet/transactions?transaction_type=credit",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert all(t["transaction_type"] == "credit" for t in data)

    async def test_get_transaction_history_pagination(self, client: AsyncClient, auth_headers, test_wallet, db_session):
        """Test transaction history pagination."""
        # Create multiple test transactions
        transactions = []
        for i in range(5):
            transaction = WalletTransaction(
                wallet_id=test_wallet.id,
                transaction_type="credit",
                amount=100.0 * (i + 1),
                description=f"Transaction {i + 1}",
                reference=f"REF_{i + 1:03d}",
                status="completed"
            )
            transactions.append(transaction)
            db_session.add(transaction)
        
        await db_session.commit()
        
        # Test pagination
        response = await client.get(
            "/api/v1/wallet/transactions?limit=2&offset=1",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert len(data) <= 2

    async def test_transfer_funds_success(self, client: AsyncClient, auth_headers, test_wallet, admin_user, db_session):
        """Test transferring funds between wallets successfully."""
        # Create receiver wallet
        receiver_wallet = Wallet(
            user_id=admin_user.id,
            balance=1000.0,
            cashback_balance=0.0,
            total_funded=1000.0,
            total_spent=0.0
        )
        db_session.add(receiver_wallet)
        await db_session.commit()
        
        transfer_data = {
            "to_user_id": admin_user.id,
            "amount": 1000.0,
            "description": "Test transfer"
        }
        
        response = await client.post(
            "/api/v1/wallet/transfer",
            json=transfer_data,
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert "debit_transaction" in data
        assert "credit_transaction" in data
        assert data["debit_transaction"]["amount"] == 1000.0
        assert data["credit_transaction"]["amount"] == 1000.0

    async def test_transfer_funds_insufficient_balance(self, client: AsyncClient, auth_headers, test_wallet, admin_user):
        """Test transferring funds with insufficient balance."""
        transfer_data = {
            "to_user_id": admin_user.id,
            "amount": 10000.0,  # More than available balance
            "description": "Test transfer"
        }
        
        response = await client.post(
            "/api/v1/wallet/transfer",
            json=transfer_data,
            headers=auth_headers
        )
        
        assert response.status_code == 400  # Bad request due to insufficient funds

    async def test_transfer_funds_to_self(self, client: AsyncClient, auth_headers, test_wallet, test_user):
        """Test transferring funds to the same user (should fail)."""
        transfer_data = {
            "to_user_id": test_user.id,
            "amount": 1000.0,
            "description": "Self transfer"
        }
        
        response = await client.post(
            "/api/v1/wallet/transfer",
            json=transfer_data,
            headers=auth_headers
        )
        
        assert response.status_code == 400  # Bad request

    async def test_transfer_funds_invalid_amount(self, client: AsyncClient, auth_headers, admin_user):
        """Test transferring invalid amount."""
        transfer_data = {
            "to_user_id": admin_user.id,
            "amount": 0.0,  # Invalid amount
            "description": "Invalid transfer"
        }
        
        response = await client.post(
            "/api/v1/wallet/transfer",
            json=transfer_data,
            headers=auth_headers
        )
        
        assert response.status_code == 422  # Validation error

    async def test_transfer_funds_missing_fields(self, client: AsyncClient, auth_headers):
        """Test transferring funds with missing required fields."""
        transfer_data = {
            "amount": 1000.0
            # Missing to_user_id and description
        }
        
        response = await client.post(
            "/api/v1/wallet/transfer",
            json=transfer_data,
            headers=auth_headers
        )
        
        assert response.status_code == 422  # Validation error

    async def test_get_transaction_by_reference_success(self, client: AsyncClient, auth_headers, test_wallet, db_session):
        """Test getting transaction by reference successfully."""
        transaction = WalletTransaction(
            wallet_id=test_wallet.id,
            transaction_type="credit",
            amount=1000.0,
            description="Test transaction",
            reference="UNIQUE_REF_123",
            status="completed"
        )
        db_session.add(transaction)
        await db_session.commit()
        await db_session.refresh(transaction)
        
        response = await client.get(
            f"/api/v1/wallet/transaction/{transaction.reference}",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["reference"] == "UNIQUE_REF_123"
        assert data["amount"] == 1000.0
        assert data["transaction_type"] == "credit"

    async def test_get_transaction_by_reference_not_found(self, client: AsyncClient, auth_headers):
        """Test getting transaction by non-existent reference."""
        response = await client.get(
            "/api/v1/wallet/transaction/NON_EXISTENT_REF",
            headers=auth_headers
        )
        
        assert response.status_code == 404

    async def test_wallet_endpoints_require_authentication(self, client: AsyncClient):
        """Test that all wallet endpoints require authentication."""
        endpoints = [
            ("/api/v1/wallet/balance", "GET"),
            ("/api/v1/wallet/fund", "POST"),
            ("/api/v1/wallet/confirm-funding", "POST"),
            ("/api/v1/wallet/transactions", "GET"),
            ("/api/v1/wallet/transfer", "POST"),
            ("/api/v1/wallet/transaction/REF123", "GET")
        ]
        
        for endpoint, method in endpoints:
            if method == "GET":
                response = await client.get(endpoint)
            else:
                response = await client.post(endpoint, json={})
            
            assert response.status_code == 401, f"Endpoint {endpoint} should require authentication"

    @pytest.mark.slow
    async def test_concurrent_wallet_operations(self, client: AsyncClient, auth_headers, test_wallet):
        """Test concurrent wallet operations for race conditions."""
        import asyncio
        
        # Simulate concurrent funding operations
        async def fund_wallet():
            funding_data = {
                "amount": 100.0,
                "payment_method": "card"
            }
            return await client.post(
                "/api/v1/wallet/fund",
                json=funding_data,
                headers=auth_headers
            )
        
        # Run multiple concurrent requests
        tasks = [fund_wallet() for _ in range(5)]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Check that all requests were handled properly
        successful_responses = [r for r in responses if not isinstance(r, Exception) and r.status_code in [200, 201]]
        assert len(successful_responses) >= 1  # At least one should succeed

    async def test_wallet_balance_precision(self, client: AsyncClient, auth_headers, test_wallet):
        """Test wallet balance precision with decimal amounts."""
        response = await client.get("/api/v1/wallet/balance", headers=auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        # Check that balance values are properly formatted
        assert isinstance(data["balance"], (int, float))
        assert isinstance(data["cashback_balance"], (int, float))
        assert isinstance(data["total_balance"], (int, float))
        
        # Verify calculations
        expected_total = data["balance"] + data["cashback_balance"]
        assert abs(data["total_balance"] - expected_total) < 0.01  # Allow for floating point precision