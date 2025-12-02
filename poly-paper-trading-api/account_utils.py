import uuid
from decimal import Decimal

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.account import Account
from models.position import Position


class CreateAccountRequest(BaseModel):
    account_name: str


class CreateAccountResponse(BaseModel):
    account_id: uuid.UUID


class SetBalanceRequest(BaseModel):
    account_name: str
    balance: Decimal


class SetBalanceResponse(BaseModel):
    account_id: uuid.UUID
    account_name: str
    balance: Decimal


class GetBalanceResponse(BaseModel):
    account_id: uuid.UUID
    account_name: str
    balance: Decimal


class PositionResponse(BaseModel):
    token_id: str
    shares: int
    total_cost: Decimal


class GetPositionsResponse(BaseModel):
    account_name: str
    positions: list[PositionResponse]


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


async def set_balance_handler(
    request: SetBalanceRequest, db: AsyncSession
) -> SetBalanceResponse:
    """Update the balance of an existing account."""
    try:
        # Find the account by name
        stmt = select(Account).where(Account.account_name == request.account_name)
        result = await db.execute(stmt)
        account = result.scalar_one_or_none()
        
        if not account:
            raise HTTPException(
                status_code=404,
                detail=f"Account with name '{request.account_name}' not found"
            )
        
        # Update the balance
        account.balance = request.balance
        await db.commit()
        await db.refresh(account)
        
        return SetBalanceResponse(
            account_id=account.account_id,
            account_name=account.account_name,
            balance=account.balance
        )
        
    except HTTPException:
        # Re-raise HTTPExceptions (like our 404 error)
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Failed to set balance: {str(e)}"
        )


async def get_balance_handler(
    account_name: str, db: AsyncSession
) -> GetBalanceResponse:
    """Get the balance of an existing account."""
    try:
        # Find the account by name
        stmt = select(Account).where(Account.account_name == account_name)
        result = await db.execute(stmt)
        account = result.scalar_one_or_none()
        
        if not account:
            raise HTTPException(
                status_code=404,
                detail=f"Account with name '{account_name}' not found"
            )
        
        return GetBalanceResponse(
            account_id=account.account_id,
            account_name=account.account_name,
            balance=account.balance
        )
        
    except HTTPException:
        # Re-raise HTTPExceptions (like our 404 error)
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get balance: {str(e)}"
        )


async def get_positions_handler(
    account_name: str, db: AsyncSession
) -> GetPositionsResponse:
    """Get all positions held by an account."""
    # Find the account by name
    stmt = select(Account).where(Account.account_name == account_name)
    result = await db.execute(stmt)
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(
            status_code=404,
            detail=f"Account with name '{account_name}' not found"
        )

    # Get all positions for this account
    stmt = select(Position).where(Position.account_id == account.account_id)
    result = await db.execute(stmt)
    positions = result.scalars().all()

    return GetPositionsResponse(
        account_name=account_name,
        positions=[
            PositionResponse(
                token_id=position.token_id,
                shares=position.shares,
                total_cost=position.total_cost,
            )
            for position in positions
        ],
    )

