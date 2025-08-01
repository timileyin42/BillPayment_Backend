import asyncio
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import get_db, Base
from app.core.config import settings
from app.database_model.user import User
from app.database_model.wallet import Wallet
from app.database_model.biller import Biller
from app.services.user_service import UserService
from app.core.security import create_access_token

# Test database URL
TEST_DATABASE_URL = "sqlite+aiosqlite:///./test.db"

# Create test engine
test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = sessionmaker(
    test_engine, class_=AsyncSession, expire_on_commit=False
)


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db_session():
    """Create a test database session."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async with TestingSessionLocal() as session:
        yield session
    
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    """Create a test client."""
    def override_get_db():
        return db_session
    
    app.dependency_overrides[get_db] = override_get_db
    
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac
    
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession):
    """Create a test user."""
    user_service = UserService(db_session)
    user_data = {
        "email": "test@example.com",
        "phone": "+2348012345678",
        "password": "TestPassword123!",
        "first_name": "Test",
        "last_name": "User"
    }
    user = await user_service.create_user(**user_data)
    return user


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession):
    """Create an admin test user."""
    user_service = UserService(db_session)
    user_data = {
        "email": "admin@example.com",
        "phone": "+2348087654321",
        "password": "AdminPassword123!",
        "first_name": "Admin",
        "last_name": "User",
        "is_admin": True
    }
    user = await user_service.create_user(**user_data)
    return user


@pytest.fixture
def test_user_token(test_user: User):
    """Create an access token for test user."""
    return create_access_token(data={"sub": test_user.email})


@pytest.fixture
def admin_user_token(admin_user: User):
    """Create an access token for admin user."""
    return create_access_token(data={"sub": admin_user.email})


@pytest_asyncio.fixture
async def test_biller(db_session: AsyncSession):
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
        fee_percentage=1.5,
        fee_cap=200.0,
        cashback_percentage=1.0,
        processing_time_minutes=5,
        is_active=True
    )
    db_session.add(biller)
    await db_session.commit()
    await db_session.refresh(biller)
    return biller


@pytest.fixture
def auth_headers(test_user_token: str):
    """Create authorization headers for test user."""
    return {"Authorization": f"Bearer {test_user_token}"}


@pytest.fixture
def admin_auth_headers(admin_user_token: str):
    """Create authorization headers for admin user."""
    return {"Authorization": f"Bearer {admin_user_token}"}


@pytest.fixture
def sample_payment_data():
    """Sample payment request data."""
    return {
        "biller_code": "TEST_ELEC",
        "customer_account": "1234567890",
        "amount": 5000.0,
        "customer_info": {
            "name": "John Doe",
            "address": "123 Test Street"
        }
    }


@pytest.fixture
def sample_wallet_funding_data():
    """Sample wallet funding request data."""
    return {
        "amount": 10000.0,
        "payment_method": "paystack",
        "payment_reference": "test_ref_123"
    }


@pytest.fixture
def sample_user_registration_data():
    """Sample user registration data."""
    return {
        "email": "newuser@example.com",
        "phone": "+2348098765432",
        "password": "NewUserPassword123!",
        "first_name": "New",
        "last_name": "User",
        "referral_code": None
    }


class MockExternalAPI:
    """Mock external API responses for testing."""
    
    @staticmethod
    def mock_successful_payment():
        return {
            "status": "success",
            "transaction_id": "ext_12345",
            "message": "Payment successful"
        }
    
    @staticmethod
    def mock_failed_payment():
        return {
            "status": "failed",
            "transaction_id": None,
            "message": "Payment failed"
        }
    
    @staticmethod
    def mock_customer_validation_success():
        return {
            "status": "success",
            "customer_name": "John Doe",
            "customer_address": "123 Test Street",
            "account_status": "active"
        }
    
    @staticmethod
    def mock_customer_validation_failed():
        return {
            "status": "failed",
            "message": "Customer not found"
        }


@pytest.fixture
def mock_external_api():
    """Provide mock external API responses."""
    return MockExternalAPI()