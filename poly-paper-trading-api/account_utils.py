import uuid

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.account import Account


class CreateAccountRequest(BaseModel):
    account_name: str


class CreateAccountResponse(BaseModel):
    account_id: uuid.UUID


async def create_account_handler(
    request: CreateAccountRequest, db: AsyncSession
) -> CreateAccountResponse:
    """Create a new account with the given name."""
    try:
        # Check if account with this name already exists
        stmt = select(Account).where(Account.account_name == request.account_name)
        result = await db.execute(stmt)
        existing_account = result.scalar_one_or_none()
        
        if existing_account:
            raise HTTPException(
                status_code=409,
                detail=f"Account with name '{request.account_name}' already exists"
            )
        
        # Create new account
        account = Account(account_name=request.account_name)
        db.add(account)
        await db.commit()
        
        return CreateAccountResponse(account_id=account.account_id)
        
    except HTTPException:
        # Re-raise HTTPExceptions (like our 409 error)
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Failed to create account: {str(e)}"
        )

