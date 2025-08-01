vision-backend/  
├── app/  
│   ├── core/  
│   │   ├── config.py           # Environment variables  
│   │   ├── database.py         # Async DB session management  
│   │   ├── security.py         # Auth/JWT utilities  
│   │   └── errors.py           # Custom HTTP exceptions  
│   │  
│   ├── database_model/         # SQLAlchemy ORM models  
│   │   ├── user.py             # User model  
│   │   ├── wallet.py           # Wallet model  
│   │   ├── transaction.py      # Payment transactions  
│   │   ├── cashback.py         # Rewards ledger  
│   │   └── biller.py           # Bill provider configs  
│   │  
│   ├── payment_model/          # Payment domain models  
│   │   ├── abstract_biller.py  # Biller interface  
│   │   ├── electricity.py      # Electricity provider impl  
│   │   ├── internet.py         # Internet provider impl  
│   │   └── provider_factory.py # Biller provider resolver  
│   │  
│   ├── services/               # Business logic  
│   │   ├── wallet_service.py   # Balance management  
│   │   ├── payment_service.py  # Bill payment processor  
│   │   ├── cashback_service.py # Reward calculations  
│   │   ├── notification.py     # SMS/email dispatcher  
│   │   └── scheduler.py        # Recurring jobs  
│   │  
│   ├── routers/                # API endpoints  
│   │   ├── auth.py             # /auth/login, /auth/register  
│   │   ├── wallet.py           # /wallet/fund, /wallet/balance  
│   │   ├── bills.py            # /bills/pay, /bills/validate  
│   │   ├── cashback.py         # /rewards/history  
│   │   └── admin.py            # Internal operations  
│   │  
│   ├── dependencies/           # DI containers  
│   │   ├── get_db.py           # DB session injector  
│   │   └── auth.py             # User authentication  
│   │  
│   ├── utils/                  # Helpers  
│   │   ├── idempotency.py      # Request deduplication  
│   │   ├── lock_manager.py     # Redis distributed locks  
│   │   └── webhooks.py         # Event notifier  
│   │  
│   ├── tasks/                  # Celery workers  
│   │   ├── recurring_payments.py  
│   │   └── reconciliation.py  
│   │  
│   └── main.py                 # App initialization  
│  
├── tests/                      # Pytest suite  
├── scripts/                    # DB migration scripts  
├── requirements.txt            # Python dependencies  
└── Dockerfile                  # Containerization  