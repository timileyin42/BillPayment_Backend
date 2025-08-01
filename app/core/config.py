from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # App Settings
    app_name: str = "Vision Fintech API"
    version: str = "1.0.0"
    debug: bool = False
    
    # Database
    database_url: str = "postgresql://postgres:password@localhost/vision_db"
    
    # Redis
    redis_url: str = "redis://localhost:6379"
    
    # Security
    secret_key: str = "your-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    
    # Cashback Settings
    default_cashback_rate: float = 0.05  # 5%
    max_cashback_rate: float = 0.10  # 10%
    min_cashback_rate: float = 0.03  # 3%
    
    # Payment Settings
    min_payment_amount: float = 100.0
    max_payment_amount: float = 1000000.0
    transaction_fee: float = 10.0
    
    # External APIs
    electricity_api_url: str = "https://api.electricity-provider.com"
    internet_api_url: str = "https://api.internet-provider.com"
    sms_api_key: Optional[str] = None
    email_api_key: Optional[str] = None
    
    class Config:
        env_file = ".env"
        case_sensitive = False

settings = Settings()