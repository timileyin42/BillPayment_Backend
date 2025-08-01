from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import async_session_maker


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency to get database session.
    
    This function creates a new database session for each request
    and ensures it's properly closed after the request is completed.
    
    Yields:
        AsyncSession: Database session
    """
    async with async_session_maker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_db_transaction() -> AsyncGenerator[AsyncSession, None]:
    """Dependency to get database session with automatic transaction management.
    
    This function creates a new database session with automatic transaction
    management. The transaction is committed if no exceptions occur,
    otherwise it's rolled back.
    
    Yields:
        AsyncSession: Database session with transaction
    """
    async with async_session_maker() as session:
        async with session.begin():
            try:
                yield session
            except Exception:
                await session.rollback()
                raise