from pydantic_settings import BaseSettings
from typing import List
from pydantic import field_validator

class TestSettings(BaseSettings):
    allowed_hosts: List[str] = ['localhost']
    
    @field_validator('allowed_hosts', mode='before')
    @classmethod
    def parse_allowed_hosts(cls, v):
        if isinstance(v, str):
            return [host.strip() for host in v.split(',')]
        return v
    
    class Config:
        env_file = '.env'
        case_sensitive = False

try:
    s = TestSettings()
    print('Config loaded successfully:', s.allowed_hosts)
except Exception as e:
    print('Error loading config:', e)
    import traceback
    traceback.print_exc()