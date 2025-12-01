import asyncio
import os
from collections.abc import AsyncGenerator

from dotenv import load_dotenv
from google.cloud.sql.connector import Connector
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

load_dotenv()

# Cloud SQL connection configuration from environment variables
INSTANCE_CONNECTION_NAME = os.environ["INSTANCE_CONNECTION_NAME"]
DB_USER = os.environ["DB_USER"]
DB_NAME = os.environ["DB_NAME"]
DB_PASS = os.environ["DB_PASS"]

# Global connector instance - initialized in lifespan
connector: Connector | None = None
engine = None
async_session_maker = None


async def init_db():
    """Initialize database connection. Must be called from within an async context."""
    global connector, engine, async_session_maker
    
    # Explicitly bind the connector to the current running event loop
    loop = asyncio.get_running_loop()
    connector = Connector(loop=loop)
    
    async def getconn():
        conn = await connector.connect_async(
            INSTANCE_CONNECTION_NAME,
            "asyncpg",
            user=DB_USER,
            password=DB_PASS,
            db=DB_NAME,
        )
        return conn

    engine = create_async_engine(
        "postgresql+asyncpg://",
        async_creator=getconn,
        echo=True,
    )
    
    async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine


async def close_db():
    """Close database connection and cleanup resources."""
    global connector, engine
    if engine:
        await engine.dispose()
    if connector:
        await connector.close_async()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    if async_session_maker is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    async with async_session_maker() as session:
        yield session
