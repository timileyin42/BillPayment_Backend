from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging
import time

from .core.config import settings
from .core.database import engine
from .core.errors import VisionException
from .api import auth, wallet, payments, billers, cashback, admin

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    logger.info("Starting Vision Fintech Backend...")
    
    # Create database tables
    try:
        from .database_model import user, wallet, transaction, cashback, biller
        from sqlalchemy import MetaData
        
        # Import all models to ensure they're registered
        logger.info("Creating database tables...")
        
        async with engine.begin() as conn:
            # Create all tables
            from .database_model.user import User
            from .database_model.wallet import Wallet, WalletTransaction
            from .database_model.transaction import Transaction, RecurringPayment
            from .database_model.cashback import Cashback, CashbackRule, ReferralReward
            from .database_model.biller import Biller, BillerStatus
            
            # Create tables
            await conn.run_sync(User.metadata.create_all)
            
        logger.info("Database tables created successfully")
        
    except Exception as e:
        logger.error(f"Failed to create database tables: {e}")
        raise
    
    yield
    
    # Shutdown
    logger.info("Shutting down Vision Fintech Backend...")
    await engine.dispose()

# Create FastAPI application
app = FastAPI(
    title="Vision Fintech Backend",
    description="Backend API for Vision Fintech bill payment application",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["*"],
)

# Add trusted host middleware for production
if settings.environment == "production":
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.allowed_hosts
    )

# Request timing middleware
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    """Add processing time to response headers."""
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response

# Global exception handler
@app.exception_handler(VisionException)
async def vision_exception_handler(request: Request, exc: VisionException):
    """Handle custom Vision exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.error_code,
            "message": exc.detail,
            "timestamp": time.time()
        }
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle general exceptions."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    
    return JSONResponse(
        status_code=500,
        content={
            "error": "INTERNAL_SERVER_ERROR",
            "message": "An internal server error occurred",
            "timestamp": time.time()
        }
    )

# Include API routers
app.include_router(auth.router, prefix="/api/v1")
app.include_router(wallet.router, prefix="/api/v1")
app.include_router(payments.router, prefix="/api/v1")
app.include_router(billers.router, prefix="/api/v1")
app.include_router(cashback.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")

# Health check endpoints
@app.get("/health")
async def health_check():
    """Basic health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "version": "1.0.0",
        "environment": settings.environment
    }

@app.get("/health/detailed")
async def detailed_health_check():
    """Detailed health check with database connectivity."""
    health_status = {
        "status": "healthy",
        "timestamp": time.time(),
        "version": "1.0.0",
        "environment": settings.environment,
        "checks": {
            "database": "unknown",
            "redis": "unknown"
        }
    }
    
    # Check database connectivity
    try:
        from .core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            await db.execute("SELECT 1")
        health_status["checks"]["database"] = "healthy"
    except Exception as e:
        health_status["checks"]["database"] = f"unhealthy: {str(e)}"
        health_status["status"] = "degraded"
    
    # Check Redis connectivity (if configured)
    try:
        import aioredis
        redis = aioredis.from_url(settings.redis_url)
        await redis.ping()
        await redis.close()
        health_status["checks"]["redis"] = "healthy"
    except Exception as e:
        health_status["checks"]["redis"] = f"unhealthy: {str(e)}"
        if health_status["status"] == "healthy":
            health_status["status"] = "degraded"
    
    return health_status

# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "message": "Welcome to Vision Fintech Backend API",
        "version": "1.0.0",
        "docs_url": "/docs",
        "redoc_url": "/redoc",
        "health_check": "/health",
        "api_prefix": "/api/v1",
        "endpoints": {
            "authentication": "/api/v1/auth",
            "wallet": "/api/v1/wallet",
            "payments": "/api/v1/payments",
            "billers": "/api/v1/billers",
            "cashback": "/api/v1/cashback",
            "admin": "/api/v1/admin"
        }
    }

# API information endpoint
@app.get("/api/v1")
async def api_info():
    """API version information."""
    return {
        "version": "1.0.0",
        "title": "Vision Fintech Backend API",
        "description": "Backend API for Vision Fintech bill payment application",
        "endpoints": {
            "auth": {
                "register": "POST /api/v1/auth/register",
                "login": "POST /api/v1/auth/login",
                "refresh": "POST /api/v1/auth/refresh",
                "profile": "GET /api/v1/auth/me",
                "dashboard": "GET /api/v1/auth/dashboard"
            },
            "wallet": {
                "balance": "GET /api/v1/wallet/balance",
                "fund": "POST /api/v1/wallet/fund",
                "transfer": "POST /api/v1/wallet/transfer",
                "transactions": "GET /api/v1/wallet/transactions"
            },
            "payments": {
                "validate": "POST /api/v1/payments/validate-customer",
                "calculate": "POST /api/v1/payments/calculate-breakdown",
                "process": "POST /api/v1/payments/process",
                "history": "GET /api/v1/payments/history",
                "recurring": "POST /api/v1/payments/recurring"
            },
            "billers": {
                "list": "GET /api/v1/billers/",
                "details": "GET /api/v1/billers/{biller_code}",
                "status": "GET /api/v1/billers/status/{biller_code}",
                "categories": "GET /api/v1/billers/categories"
            },
            "cashback": {
                "history": "GET /api/v1/cashback/history",
                "summary": "GET /api/v1/cashback/summary",
                "rules": "GET /api/v1/cashback/rules",
                "calculate": "GET /api/v1/cashback/calculate",
                "claim": "POST /api/v1/cashback/claim/{cashback_id}",
                "leaderboard": "GET /api/v1/cashback/leaderboard",
                "stats": "GET /api/v1/cashback/stats",
                "referrals": "GET /api/v1/cashback/referrals",
                "referrals_history": "GET /api/v1/cashback/referrals/history"
            },
            "admin": {
                "cashback_rules": "GET /api/v1/admin/cashback/rules",
                "create_rule": "POST /api/v1/admin/cashback/rules",
                "update_rule": "PUT /api/v1/admin/cashback/rules/{rule_id}",
                "delete_rule": "DELETE /api/v1/admin/cashback/rules/{rule_id}",
                "cashback_summary": "GET /api/v1/admin/cashback/summary",
                "user_cashback": "GET /api/v1/admin/cashback/users/{user_id}",
                "process_cashback": "POST /api/v1/admin/cashback/process",
                "bulk_process": "POST /api/v1/admin/cashback/bulk-process"
            }
        }
    }

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True if settings.environment == "development" else False,
        log_level="info"
    )