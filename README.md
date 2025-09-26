# Vision Fintech Backend 🏦

A comprehensive fintech backend system for bill payments, wallet management, and cashback rewards built with FastAPI and modern Python technologies.


## 🚀 Features

### Core Functionality
- **User Management**: Registration, authentication, profile management
- **Wallet System**: Multi-currency wallet with funding and transaction tracking
- **Bill Payments**: Integration with multiple biller providers
- **Cashback Rewards**: Automated cashback calculation and distribution
- **Referral System**: User referral tracking and rewards
- **Admin Dashboard**: Comprehensive admin controls and analytics

### Technical Features
- **FastAPI Framework**: High-performance async API with automatic documentation
- **JWT Authentication**: Secure token-based authentication
- **Database ORM**: SQLAlchemy with Alembic migrations
- **External Integrations**: Paystack, Flutterwave payment gateways
- **Comprehensive Testing**: 130+ test cases with pytest
- **Docker Support**: Containerized deployment
- **API Documentation**: Auto-generated OpenAPI/Swagger docs

## 🏗️ System Architecture

```mermaid
graph TB
    subgraph "Client Layer"
        Mobile["📱 Mobile App"]
        Web["🌐 Web App"]
        Admin["👨‍💼 Admin Panel"]
    end
    
    subgraph "API Gateway"
        Gateway["🚪 API Gateway"]
        Auth["🔐 Authentication"]
        RateLimit["⏱️ Rate Limiting"]
    end
    
    subgraph "FastAPI Application"
        AuthAPI["👤 Auth API"]
        WalletAPI["💰 Wallet API"]
        PaymentAPI["💳 Payment API"]
        BillerAPI["🏢 Biller API"]
        CashbackAPI["🎁 Cashback API"]
        AdminAPI["⚙️ Admin API"]
    end
    
    subgraph "Business Logic"
        AuthService["Auth Service"]
        WalletService["Wallet Service"]
        PaymentService["Payment Service"]
        BillerService["Biller Service"]
        CashbackService["Cashback Service"]
    end
    
    subgraph "Data Layer"
        PostgreSQL[("🗄️ PostgreSQL")]
        Redis[("⚡ Redis Cache")]
    end
    
    subgraph "External Services"
        Paystack["💳 Paystack"]
        Flutterwave["💳 Flutterwave"]
        Billers["🏢 Biller APIs"]
    end
    
    Mobile --> Gateway
    Web --> Gateway
    Admin --> Gateway
    
    Gateway --> Auth
    Auth --> RateLimit
    RateLimit --> AuthAPI
    RateLimit --> WalletAPI
    RateLimit --> PaymentAPI
    RateLimit --> BillerAPI
    RateLimit --> CashbackAPI
    RateLimit --> AdminAPI
    
    AuthAPI --> AuthService
    WalletAPI --> WalletService
    PaymentAPI --> PaymentService
    BillerAPI --> BillerService
    CashbackAPI --> CashbackService
    AdminAPI --> AuthService
    
    AuthService --> PostgreSQL
    WalletService --> PostgreSQL
    PaymentService --> PostgreSQL
    BillerService --> PostgreSQL
    CashbackService --> PostgreSQL
    
    WalletService --> Redis
    PaymentService --> Redis
    
    WalletService --> Paystack
    WalletService --> Flutterwave
    PaymentService --> Billers
    
    style Mobile fill:#e3f2fd
    style Web fill:#e3f2fd
    style Admin fill:#e3f2fd
    style PostgreSQL fill:#e8f5e8
    style Redis fill:#ffebee
    style Paystack fill:#fff3e0
    style Flutterwave fill:#fff3e0
    style Billers fill:#fff3e0
```


```mermaid
sequenceDiagram
    participant User
    participant API
    participant WalletService
    participant PaymentService
    participant BillerAPI
    participant CashbackService
    participant Database
    
    User->>API: Select Biller & Enter Details
    API->>BillerAPI: Validate Customer Account
    BillerAPI-->>API: Customer Details
    API-->>User: Show Payment Breakdown
    
    User->>API: Confirm Payment
    API->>WalletService: Check Balance
    WalletService->>Database: Get Wallet Balance
    Database-->>WalletService: Balance Info
    WalletService-->>API: Balance Sufficient
    
    API->>PaymentService: Process Payment
    PaymentService->>WalletService: Debit Wallet
    WalletService->>Database: Update Balance
    PaymentService->>BillerAPI: Submit Payment
    BillerAPI-->>PaymentService: Payment Confirmation
    
    PaymentService->>CashbackService: Calculate Cashback
    CashbackService->>Database: Create Cashback Record
    CashbackService->>WalletService: Credit Cashback
    WalletService->>Database: Update Cashback Balance
    
    PaymentService->>Database: Update Transaction Status
    PaymentService-->>API: Payment Complete
    API-->>User: Success + Cashback Info
```


### Core Entities
- **Users**: Account management and authentication
- **Wallets**: Balance tracking and transaction history
- **Transactions**: Bill payment records and status
- **Billers**: Payment provider configurations
- **Cashbacks**: Reward calculation and distribution
- **Referrals**: User referral tracking and bonuses

[View Detailed Database Schema →](docs/database-schema.md)

## 🔧 Quick Start

### Prerequisites
- Python 3.10+
- PostgreSQL 12+
- Redis 6+
- Docker (optional)

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/your-org/vision-fintech-backend.git
   cd vision-fintech-backend
   ```

2. **Set up virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Configure environment variables**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

4. **Set up database**
   ```bash
   # Create database
   createdb vision_fintech
   
   # Run migrations
   alembic upgrade head
   
   # Seed initial data
   python scripts/seed_data.py
   ```

5. **Start the application**
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

### Docker Setup

```bash
# Build and run with Docker Compose
docker-compose up --build

# The API will be available at http://localhost:8000
```

## 📚 API Documentation

### Interactive Documentation
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### API Endpoints Overview

| Endpoint | Description | Authentication |
|----------|-------------|----------------|
| `POST /auth/register` | User registration | ❌ |
| `POST /auth/login` | User authentication | ❌ |
| `GET /wallet/balance` | Get wallet balance | ✅ |
| `POST /wallet/fund` | Fund wallet | ✅ |
| `GET /billers` | List available billers | ✅ |
| `POST /payments/pay-bill` | Process bill payment | ✅ |
| `GET /cashback/history` | Cashback history | ✅ |
| `GET /admin/analytics` | Admin dashboard | 👨‍💼 |

[View Complete API Documentation →](docs/api-structure.md)

## 🧪 Testing

### Run Tests
```bash
# Run all tests
python run_tests.py

# Run specific test categories
python run_tests.py --category unit
python run_tests.py --category integration
python run_tests.py --category api

# Run with coverage
python run_tests.py --coverage

# Run in parallel
python run_tests.py --parallel
```

### Test Coverage
- **Unit Tests**: 85+ test cases
- **Integration Tests**: 30+ test cases
- **API Tests**: 20+ test cases
- **Overall Coverage**: 95%+

## 🔒 Security Features

### Authentication & Authorization
- JWT token-based authentication
- Role-based access control (User, Admin)
- Password hashing with bcrypt
- Token expiration and refresh

### API Security
- Rate limiting per endpoint
- CORS configuration
- Input validation and sanitization
- SQL injection prevention
- XSS protection headers

### Data Protection
- Encrypted sensitive data
- PCI DSS compliance considerations
- Audit logging for financial transactions
- Secure external API communications

## 🚀 Deployment

### Production Deployment

1. **Environment Setup**
   ```bash
   # Set production environment variables
   export ENVIRONMENT=production
   export DATABASE_URL=postgresql://...
   export REDIS_URL=redis://...
   ```

2. **Database Migration**
   ```bash
   alembic upgrade head
   ```

3. **Start Application**
   ```bash
   gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker
   ```

### Docker Production
```bash
# Build production image
docker build -t vision-fintech-backend:latest .

# Run with production compose
docker-compose -f docker-compose.prod.yml up -d
```

### Health Checks
- **Basic Health**: `GET /health`
- **Detailed Health**: `GET /health/detailed`
- **Database Status**: Included in detailed health check
- **External Services**: Monitor biller API connectivity

## 📊 Monitoring & Analytics

### Application Metrics
- Request/response times
- Error rates and types
- Database query performance
- External API response times

### Business Metrics
- Transaction volumes and success rates
- User registration and activity
- Cashback distribution
- Revenue and fee collection

### Logging
- Structured JSON logging
- Transaction audit trails
- Error tracking and alerting
- Performance monitoring

## 🔧 Configuration

### Environment Variables

```bash
# Database
DATABASE_URL=postgresql://user:pass@localhost/vision_fintech
REDIS_URL=redis://localhost:6379

# Security
SECRET_KEY=your-secret-key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# External Services
PAYSTACK_SECRET_KEY=sk_test_...
FLUTTERWAVE_SECRET_KEY=FLWSECK_TEST...

# Application
ENVIRONMENT=development
DEBUG=true
ALLOWED_HOSTS=localhost,127.0.0.1
```

### Feature Flags
- Cashback system enable/disable
- Referral program toggle
- Maintenance mode
- New biller integration testing

## 🤝 Contributing

### Development Workflow
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Run the test suite
6. Submit a pull request

### Code Standards
- Follow PEP 8 style guidelines
- Use type hints for all functions
- Write comprehensive docstrings
- Maintain test coverage above 90%

### Commit Convention
```
feat: add new cashback calculation method
fix: resolve wallet balance synchronization issue
docs: update API documentation
test: add integration tests for payment flow
```

## 📋 Project Structure

```
vision-fintech-backend/
├── app/
│   ├── api/                 # API route handlers
│   ├── core/                # Core configuration
│   ├── database_model/      # SQLAlchemy models
│   ├── dependencies/        # FastAPI dependencies
│   ├── payment_model/       # Payment abstractions
│   ├── services/           # Business logic services
│   └── main.py             # FastAPI application
├── tests/                  # Test suite
├── docs/                   # Documentation
├── scripts/                # Utility scripts
├── alembic/               # Database migrations
├── requirements.txt       # Python dependencies
├── Dockerfile            # Container configuration
└── docker-compose.yml    # Multi-container setup
```

## 📈 Roadmap

### Phase 1 (Current)
- ✅ Core bill payment functionality
- ✅ Wallet management system
- ✅ Cashback rewards
- ✅ User authentication

### Phase 2 (Q2 2024)
- 🔄 Mobile app integration
- 🔄 Advanced analytics dashboard
- 🔄 Recurring payment automation
- 🔄 Multi-currency support

### Phase 3 (Q3 2024)
- 📋 Merchant payment gateway
- 📋 Investment products integration
- 📋 Advanced fraud detection
- 📋 API marketplace

## 📞 Support

### Documentation
- [System Architecture](docs/architecture.md)
- [API Structure](docs/api-structure.md)
- [Database Schema](docs/database-schema.md)
- [Workflow Diagrams](docs/workflows.md)

### Contact
- **Email**: support@visionfintech.com
- **Documentation**: https://docs.visionfintech.com
- **Issues**: GitHub Issues
- **Discussions**: GitHub Discussions

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

**Built with ❤️ by the Vision Fintech Team**

![Footer Image](https://trae-api-sg.mchost.guru/api/ide/v1/text_to_image?prompt=modern%20fintech%20technology%20banner%20with%20digital%20payment%20icons%2C%20mobile%20banking%20symbols%2C%20and%20financial%20graphics%20in%20a%20professional%20blue%20gradient%20style&image_size=landscape_16_9)