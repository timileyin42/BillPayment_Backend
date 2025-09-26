from pydantic_settings import BaseSettings
from typing import Optional, List
from pydantic import field_validator

class Settings(BaseSettings):
    # App Settings
    app_name: str = "Vision Fintech API"
    version: str = "1.0.0"
    debug: bool = False
    environment: str = "development"
    
    # Database
    database_url: str = "postgresql://postgres:password@localhost/vision_db"
    
    # Redis
    redis_url: str = "redis://localhost:6379"
    
    # Security
    secret_key: str = "your-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    
    # CORS and Host Settings
    allowed_hosts: List[str] = ["localhost", "127.0.0.1", "0.0.0.0"]
    
    @field_validator('allowed_hosts', mode='before')
    @classmethod
    def parse_allowed_hosts(cls, v):
        if isinstance(v, str):
            return [host.strip() for host in v.split(',')]
        return v
    
    # Middleware Settings
    rate_limit_requests_per_minute: int = 100
    rate_limit_requests_per_hour: int = 1000
    max_request_size: int = 10 * 1024 * 1024  # 10MB
    session_timeout: int = 3600  # 1 hour
    max_concurrent_sessions: int = 5
    enable_csrf_protection: bool = True
    enable_audit_logging: bool = True
    enable_ip_filtering: bool = True
    max_failed_attempts: int = 5
    block_duration: int = 300  # 5 minutes
    
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
    
    @property
    def ALLOWED_HOSTS(self) -> list[str]:
        """Get allowed hosts for CORS and TrustedHost middleware."""
        return self.allowed_hosts
    
    @property
    def SECRET_KEY(self) -> str:
        """Get secret key for middleware."""
        return self.secret_key
    
    @property
    def ENVIRONMENT(self) -> str:
        """Get environment setting."""
        return self.environment
    
    class Config:
        env_file = ".env"
        case_sensitive = False

settings = Settings()