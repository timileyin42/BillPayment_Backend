# Vision Fintech Backend - Test Suite

This directory contains comprehensive test suites for the Vision Fintech Backend application, covering wallet functionality, payment processing, and transaction management.

## Test Structure

### Test Files

- **`conftest.py`** - Test configuration and shared fixtures
- **`test_wallet_service.py`** - Unit tests for wallet service business logic
- **`test_wallet_api.py`** - API endpoint tests for wallet functionality
- **`test_payment_service.py`** - Unit tests for payment service business logic
- **`test_payment_api.py`** - API endpoint tests for payment functionality
- **`run_tests.py`** - Test runner script with various options

### Test Categories

Tests are organized using pytest markers:

- **`@pytest.mark.unit`** - Unit tests for business logic
- **`@pytest.mark.integration`** - Integration tests
- **`@pytest.mark.api`** - API endpoint tests
- **`@pytest.mark.wallet`** - Wallet-related tests
- **`@pytest.mark.payment`** - Payment-related tests
- **`@pytest.mark.cashback`** - Cashback-related tests
- **`@pytest.mark.auth`** - Authentication tests
- **`@pytest.mark.biller`** - Biller-related tests
- **`@pytest.mark.slow`** - Tests that take longer to run

## Test Coverage

### Wallet Service Tests (`test_wallet_service.py`)

#### Core Wallet Operations
- ✅ Get wallet by user ID (success/not found)
- ✅ Create new wallet for user
- ✅ Get wallet balance (main + cashback)

#### Funding Operations
- ✅ Fund wallet with valid amounts
- ✅ Validate funding amounts (minimum/maximum)
- ✅ Handle invalid payment methods
- ✅ Confirm pending funding transactions
- ✅ Handle transaction not found scenarios

#### Debit Operations
- ✅ Debit from main balance
- ✅ Debit using cashback balance
- ✅ Combined debit (main + cashback)
- ✅ Insufficient funds handling
- ✅ Invalid amount validation

#### Cashback Operations
- ✅ Add cashback to user wallet
- ✅ Cashback amount validation

#### Transaction History
- ✅ Retrieve transaction history
- ✅ Filter by transaction type
- ✅ Filter by date range
- ✅ Pagination support
- ✅ Get transaction by reference

#### Transfer Operations
- ✅ Transfer funds between users
- ✅ Insufficient balance handling
- ✅ Self-transfer prevention
- ✅ Invalid recipient handling

### Wallet API Tests (`test_wallet_api.py`)

#### Authentication
- ✅ All endpoints require authentication
- ✅ Unauthorized access handling

#### Wallet Balance Endpoints
- ✅ GET `/api/v1/wallet/balance` - Get wallet balance
- ✅ Handle users without wallets

#### Funding Endpoints
- ✅ POST `/api/v1/wallet/fund` - Fund wallet
- ✅ Input validation (amount, payment method)
- ✅ POST `/api/v1/wallet/confirm-funding` - Confirm funding

#### Transaction History Endpoints
- ✅ GET `/api/v1/wallet/transactions` - Get transaction history
- ✅ Query parameters (type, start_date, end_date, limit, offset)
- ✅ GET `/api/v1/wallet/transactions/{reference}` - Get by reference

#### Transfer Endpoints
- ✅ POST `/api/v1/wallet/transfer` - Transfer funds
- ✅ Input validation and business rule enforcement

### Payment Service Tests (`test_payment_service.py`)

#### Biller Management
- ✅ Get biller by code (success/not found)
- ✅ Get active billers (all/filtered by type)
- ✅ Biller ordering (featured first)

#### Customer Validation
- ✅ Validate customer with external APIs
- ✅ Handle biller not found
- ✅ Handle inactive billers
- ✅ External service error handling

#### Payment Breakdown
- ✅ Calculate payment breakdown (fees, cashback, totals)
- ✅ Amount validation (min/max limits)
- ✅ Cashback calculation integration

#### Payment Processing
- ✅ Process payments successfully
- ✅ Wallet balance validation
- ✅ Transaction creation and reference generation
- ✅ Cashback balance usage
- ✅ External biller integration

#### Transaction Management
- ✅ Get transaction by reference
- ✅ Get user transactions with filters
- ✅ Transaction pagination
- ✅ Update transaction status
- ✅ Refund transactions

#### Recurring Payments
- ✅ Create recurring payment schedules
- ✅ Get user recurring payments
- ✅ Filter active/inactive recurring payments

### Payment API Tests (`test_payment_api.py`)

#### Biller Endpoints
- ✅ GET `/api/v1/billers` - Get all billers
- ✅ GET `/api/v1/billers?bill_type=X` - Filter by type
- ✅ GET `/api/v1/billers/{code}` - Get specific biller

#### Customer Validation Endpoints
- ✅ POST `/api/v1/payments/validate-customer` - Validate customer
- ✅ Authentication required
- ✅ Input validation

#### Payment Calculation Endpoints
- ✅ POST `/api/v1/payments/calculate-breakdown` - Calculate payment breakdown
- ✅ Authentication and validation

#### Payment Processing Endpoints
- ✅ POST `/api/v1/payments/process` - Process payment
- ✅ Comprehensive input validation
- ✅ Authentication required

#### Transaction Endpoints
- ✅ GET `/api/v1/payments/transactions/{reference}` - Get by reference
- ✅ GET `/api/v1/payments/transactions` - Get user transactions
- ✅ Query filters and pagination
- ✅ Authentication required

#### Recurring Payment Endpoints
- ✅ POST `/api/v1/payments/recurring` - Create recurring payment
- ✅ GET `/api/v1/payments/recurring` - Get recurring payments
- ✅ Filter active/inactive

#### Admin Endpoints
- ✅ PATCH `/api/v1/payments/transactions/{id}/status` - Update status (admin only)
- ✅ POST `/api/v1/payments/transactions/{id}/refund` - Refund (admin only)
- ✅ Admin privilege validation

## Running Tests

### Prerequisites

```bash
# Install test dependencies
pip install pytest pytest-asyncio pytest-cov
```

### Basic Usage

```bash
# Run all tests
python run_tests.py

# Or use pytest directly
pytest tests/
```

### Test Categories

```bash
# Run only unit tests
python run_tests.py --unit

# Run only API tests
python run_tests.py --api

# Run only integration tests
python run_tests.py --integration
```

### Module-Specific Tests

```bash
# Run only wallet tests
python run_tests.py --wallet

# Run only payment tests
python run_tests.py --payment

# Run only cashback tests
python run_tests.py --cashback
```

### Coverage Reports

```bash
# Run with coverage report
python run_tests.py --coverage

# Generate HTML coverage report
python run_tests.py --coverage --html
```

### Performance Options

```bash
# Skip slow tests
python run_tests.py --fast

# Run tests in parallel
python run_tests.py --parallel 4
```

### Specific Tests

```bash
# Run specific test file
python run_tests.py --file test_wallet_service.py

# Run specific test function
python run_tests.py --test test_fund_wallet_success
```

### Debug Options

```bash
# Verbose output
python run_tests.py --verbose

# Stop on first failure
python run_tests.py --failfast

# Drop into debugger on failure
python run_tests.py --pdb
```

## Test Configuration

### Environment Variables

Tests use the following environment variables (set in `pytest.ini`):

- `ENVIRONMENT=testing`
- `DATABASE_URL=sqlite+aiosqlite:///:memory:`
- `REDIS_URL=redis://localhost:6379/1`
- `SECRET_KEY=test_secret_key_for_testing_only`
- `ACCESS_TOKEN_EXPIRE_MINUTES=30`
- `REFRESH_TOKEN_EXPIRE_DAYS=7`

### Test Database

Tests use an in-memory SQLite database that is created fresh for each test session. This ensures:

- Fast test execution
- Complete isolation between tests
- No dependency on external databases

### Fixtures

Key fixtures available in `conftest.py`:

- `db_session` - Async database session
- `test_client` - FastAPI test client
- `test_user` - Regular test user
- `admin_user` - Admin test user
- `test_auth_headers` - Authentication headers for regular user
- `admin_auth_headers` - Authentication headers for admin user
- `test_biller` - Sample biller for testing
- `sample_payment_data` - Sample payment data
- `MockExternalAPI` - Mock external API responses

## Test Data

### Sample Users

```python
# Regular test user
{
    "email": "test@example.com",
    "phone_number": "+2348012345678",
    "first_name": "Test",
    "last_name": "User",
    "is_active": True,
    "is_verified": True
}

# Admin test user
{
    "email": "admin@example.com",
    "phone_number": "+2348087654321",
    "first_name": "Admin",
    "last_name": "User",
    "is_active": True,
    "is_verified": True,
    "is_admin": True
}
```

### Sample Biller

```python
{
    "name": "Test Electricity Company",
    "code": "TEST_ELEC",
    "bill_type": "electricity",
    "category": "utilities",
    "min_amount": 100.0,
    "max_amount": 50000.0,
    "transaction_fee": 50.0,
    "cashback_rate": 2.0,
    "is_active": True
}
```

## Best Practices

### Writing Tests

1. **Use descriptive test names** that clearly indicate what is being tested
2. **Follow the AAA pattern** (Arrange, Act, Assert)
3. **Test both success and failure scenarios**
4. **Use appropriate markers** to categorize tests
5. **Mock external dependencies** to ensure test isolation
6. **Keep tests independent** - each test should be able to run in isolation

### Test Organization

1. **Group related tests** in the same test class
2. **Use fixtures** for common setup and teardown
3. **Separate unit tests from integration tests**
4. **Test edge cases and error conditions**
5. **Maintain good test coverage** (aim for >80%)

### Performance

1. **Use async fixtures** for database operations
2. **Mock external API calls** to avoid network dependencies
3. **Use in-memory database** for fast test execution
4. **Mark slow tests** with `@pytest.mark.slow`
5. **Run tests in parallel** when possible

## Continuous Integration

For CI/CD pipelines, use:

```bash
# Run all tests with coverage
python run_tests.py --coverage --failfast

# Or with pytest directly
pytest tests/ --cov=app --cov-report=xml --cov-fail-under=80
```

## Troubleshooting

### Common Issues

1. **Import errors** - Ensure the project root is in PYTHONPATH
2. **Database errors** - Check that async database fixtures are used correctly
3. **Authentication errors** - Ensure test auth headers are used for protected endpoints
4. **Mock errors** - Verify that external dependencies are properly mocked

### Debug Tips

1. Use `--pdb` flag to drop into debugger on failures
2. Use `--verbose` flag for detailed test output
3. Run specific tests to isolate issues
4. Check test logs for detailed error information

## Contributing

When adding new features:

1. **Write tests first** (TDD approach)
2. **Ensure good coverage** of new code
3. **Update this README** if adding new test categories
4. **Use appropriate markers** for new tests
5. **Follow existing patterns** for consistency