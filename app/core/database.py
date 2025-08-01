from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import DeclarativeBase
from .config import settings

class Base(DeclarativeBase):
    pass

# Convert postgres:// to postgresql+asyncpg:// for async support
database_url = settings.database_url.replace("postgresql://", "postgresql+asyncpg://")

engine = create_async_engine(
    database_url,
    echo=settings.debug,
    future=True
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def get_database_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()