from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from account_utils import (
    CreateAccountRequest,
    CreateAccountResponse,
    SetBalanceRequest,
    SetBalanceResponse,
    create_account_handler,
    set_balance_handler,
)
from database import close_db, get_db, init_db
from models.account import Base


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database connection in the running event loop
    engine = await init_db()
    # Create tables on startup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Cleanup on shutdown
    await close_db()


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.post("/accounts", response_model=CreateAccountResponse)
async def create_account(
    request: CreateAccountRequest, db: AsyncSession = Depends(get_db)
) -> CreateAccountResponse:
    """Create a new account with the given name."""
    return await create_account_handler(request, db)


@app.put("/accounts/balance", response_model=SetBalanceResponse)
async def set_balance(
    request: SetBalanceRequest, db: AsyncSession = Depends(get_db)
) -> SetBalanceResponse:
    """Update the balance of an existing account."""
    return await set_balance_handler(request, db)
