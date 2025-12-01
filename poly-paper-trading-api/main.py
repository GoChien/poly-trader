import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from database import close_db, get_db, init_db
from models.account import Account, Base


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


class CreateAccountRequest(BaseModel):
    account_name: str


class CreateAccountResponse(BaseModel):
    account_id: uuid.UUID


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.post("/accounts", response_model=CreateAccountResponse)
async def create_account(
    request: CreateAccountRequest, db: AsyncSession = Depends(get_db)
) -> CreateAccountResponse:
    """Create a new account with the given name."""
    account = Account(account_name=request.account_name)
    db.add(account)
    try:
        await db.commit()
        await db.refresh(account)
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create account: {str(e)}")

    return CreateAccountResponse(account_id=account.account_id)
