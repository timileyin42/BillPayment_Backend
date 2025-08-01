# Vision Fintech Backend

A comprehensive FastAPI-based backend for a bill payment fintech application with wallet management, cashback rewards, and recurring payments.

## Features

### Core Functionality
- **User Management**: Registration, authentication, profile management
- **Wallet System**: Fund wallet, transfer money, transaction history
- **Bill Payments**: Pay electricity, internet, airtime, water, and other bills
- **Cashback & Rewards**: Earn cashback on payments and referral bonuses
- **Recurring Payments**: Set up automatic bill payments
- **Multi-Biller Support**: Integrate with multiple service providers

### Technical Features
- **Async/Await**: Built with FastAPI and async SQLAlchemy
- **Database**: PostgreSQL with Alembic migrations
- **Caching**: Redis for session management and caching
- **Security**: JWT authentication, password hashing, input validation
- **API Documentation**: Auto-generated OpenAPI/Swagger docs
- **Error Handling**: Comprehensive error handling and logging
- **Background Tasks**: Celery for scheduled and background processing

## Project Structure

```
BillPayment_Backend/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI application entry point
│   ├── core/
│   │   ├── config.py          # Application configuration
│   │   ├── database.py        # Database connection setup
│   │   ├── security.py        # Authentication and security
│   │   └── errors.py          # Custom exception classes
│   ├── database_model/
│   │   ├── user.py            # User model
│   │   ├── wallet.py          # Wallet and transaction models
│   │   ├── transaction.py     # Payment transaction models
│   │   ├── cashback.py        # Cashback and reward models
│   │   └── biller.py          # Biller and status models
│   ├── payment_model/
│   │   ├── abstract_biller.py # Abstract biller interface
│   │   ├── electricity.py     # Electricity biller implementation
│   │   ├── internet.py        # Internet/Cable TV biller
│   │   └── provider_factory.py# Biller factory and implementations
│   ├── services/
│   │   ├── user_service.py    # User business logic
│   │   ├── wallet_service.py  # Wallet operations
│   │   ├── payment_service.py # Payment processing
│   │   ├── cashback_service.py# Cashback calculations
│   │   ├── notification.py   # SMS/Email notifications
│   │   └── scheduler.py       # Background task scheduling
│   └── api/
│       ├── auth.py            # Authentication endpoints
│       ├── wallet.py          # Wallet management endpoints
│       ├── payments.py        # Payment processing endpoints
│       └── billers.py         # Biller management endpoints
├── alembic/                   # Database migration files
├── requirements.txt           # Python dependencies
├── .env.example              # Environment variables template
├── alembic.ini               # Alembic configuration
└── README.md                 # This file
```

## Installation

### Prerequisites
- Python 3.8+
- PostgreSQL 12+
- Redis 6+

### Setup

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd BillPayment_Backend
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

5. **Set up database**
   ```bash
   # Create PostgreSQL database
   createdb vision_fintech
   
   # Run migrations
   alembic upgrade head
   ```

6. **Start Redis server**
   ```bash
   redis-server
   ```

7. **Run the application**
   ```bash
   uvicorn app.main:app --reload
   ```

## Configuration

### Environment Variables

Copy `.env.example` to `.env` and configure the following:

#### Database
```env
DATABASE_URL=postgresql+asyncpg://username:password@localhost:5432/vision_fintech
```

#### Security
```env
SECRET_KEY=your-super-secret-key-change-this-in-production
ACCESS_TOKEN_EXPIRE_MINUTES=30
```

#### External APIs
```env
PAYSTACK_SECRET_KEY=sk_test_your_paystack_secret_key
FLUTTERWAVE_SECRET_KEY=FLWSECK_TEST-your_flutterwave_secret_key
```

#### Notifications
```env
SMS_API_KEY=your_sms_api_key
EMAIL_USERNAME=your-email@gmail.com
```

## API Documentation

Once the application is running, visit:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### Main Endpoints

#### Authentication
- `POST /api/v1/auth/register` - Register new user
- `POST /api/v1/auth/login` - User login
- `GET /api/v1/auth/me` - Get current user info
- `GET /api/v1/auth/dashboard` - User dashboard data

#### Wallet Management
- `GET /api/v1/wallet/balance` - Get wallet balance
- `POST /api/v1/wallet/fund` - Fund wallet
- `POST /api/v1/wallet/transfer` - Transfer to another user
- `GET /api/v1/wallet/transactions` - Transaction history

#### Bill Payments
- `GET /api/v1/billers/` - List available billers
- `POST /api/v1/payments/validate-customer` - Validate customer account
- `POST /api/v1/payments/calculate-breakdown` - Calculate payment fees
- `POST /api/v1/payments/process` - Process payment
- `GET /api/v1/payments/history` - Payment history

#### Recurring Payments
- `POST /api/v1/payments/recurring` - Set up recurring payment
- `GET /api/v1/payments/recurring` - List recurring payments

## Database Schema

### Key Models

#### User
- Authentication (email, phone, password)
- Profile information
- Referral system
- Admin flags

#### Wallet
- Balance tracking (main + cashback)
- Transaction history
- Funding and spending records

#### Transaction
- Bill payment records
- Status tracking
- Fee and cashback calculations
- External reference management

#### Biller
- Service provider information
- API configuration
- Fee structures
- Validation rules

#### Cashback
- Reward calculations
- Rule-based cashback rates
- Referral bonuses

## Business Logic

### Payment Flow
1. **Customer Validation**: Verify account with biller
2. **Payment Calculation**: Calculate fees and cashback
3. **Wallet Debit**: Deduct amount from user wallet
4. **Biller Processing**: Send payment to external biller
5. **Status Updates**: Track payment status
6. **Cashback Credit**: Award cashback on successful payment
7. **Notifications**: Send SMS/email confirmations

### Cashback System
- Base rate: 1% on all payments
- Biller-specific rates
- Amount-based tiers
- Monthly limits
- Referral bonuses: ₦500 per successful referral

### Recurring Payments
- Weekly, monthly, quarterly frequencies
- Auto-pay with wallet balance
- Insufficient funds handling
- Notification system

## Development

### Running Tests
```bash
pytest
```

### Database Migrations
```bash
# Create new migration
alembic revision --autogenerate -m "Description"

# Apply migrations
alembic upgrade head

# Rollback migration
alembic downgrade -1
```

### Code Quality
```bash
# Format code
black app/

# Lint code
flake8 app/

# Type checking
mypy app/
```

## Deployment

### Production Setup

1. **Environment Configuration**
   ```env
   ENVIRONMENT=production
   DEBUG=false
   ```

2. **Database**
   - Use managed PostgreSQL service
   - Enable connection pooling
   - Set up read replicas for scaling

3. **Redis**
   - Use managed Redis service
   - Enable persistence
   - Set up clustering for high availability

4. **Application Server**
   ```bash
   gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker
   ```

5. **Background Tasks**
   ```bash
   celery -A app.tasks worker --loglevel=info
   celery -A app.tasks beat --loglevel=info
   ```

### Docker Deployment

```dockerfile
FROM python:3.9-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## Monitoring

### Health Checks
- `GET /health` - Basic health check
- `GET /health/detailed` - Database and Redis connectivity

### Logging
- Structured logging with timestamps
- Error tracking with stack traces
- Request/response logging
- Performance metrics

### Metrics
- API response times
- Database query performance
- Payment success rates
- User activity metrics

## Security

### Authentication
- JWT tokens with expiration
- Refresh token rotation
- Password hashing with bcrypt
- Rate limiting on auth endpoints

### Data Protection
- Input validation and sanitization
- SQL injection prevention
- XSS protection
- CORS configuration
- Sensitive data encryption

### API Security
- HTTPS enforcement
- Request size limits
- Authentication required for all endpoints
- Admin-only endpoints protection

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Ensure all tests pass
6. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For support and questions:
- Email: support@visionfintech.com
- Documentation: [API Docs](http://localhost:8000/docs)
- Issues: [GitHub Issues](https://github.com/your-repo/issues)