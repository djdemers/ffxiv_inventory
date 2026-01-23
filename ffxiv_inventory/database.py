"""Database connection and initialization."""

from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .models import Base


class Database:
    """Database connection manager."""
    
    def __init__(self, database_url: str = "sqlite+aiosqlite:///./inventory.db"):
        """Initialize database connection.
        
        Args:
            database_url: SQLAlchemy database URL (default: SQLite in current directory)
        """
        self.engine: AsyncEngine = create_async_engine(
            database_url,
            echo=False,  # Set to True for SQL debugging
        )
        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
    
    async def init_db(self) -> None:
        """Initialize database tables."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get database session.
        
        Yields:
            AsyncSession for database operations
        """
        async with self.session_factory() as session:
            try:
                yield session
            finally:
                await session.close()
    
    async def close(self) -> None:
        """Close database connection."""
        await self.engine.dispose()


# Global database instance
_database: Database | None = None


def get_database(database_url: str = "sqlite+aiosqlite:///./inventory.db") -> Database:
    """Get or create global database instance.
    
    Args:
        database_url: SQLAlchemy database URL
        
    Returns:
        Database instance
    """
    global _database
    if _database is None:
        _database = Database(database_url)
    return _database


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for database sessions.
    
    Yields:
        AsyncSession for database operations
    """
    db = get_database()
    async for session in db.get_session():
        yield session
