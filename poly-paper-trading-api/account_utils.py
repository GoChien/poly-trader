import json
import uuid
from decimal import Decimal

import httpx
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.account import Account, AccountValue
from models.position import Position

POLYMARKET_CLOB_URL = "https://clob.polymarket.com"
POLYMARKET_GAMMA_URL = "https://gamma-api.polymarket.com"


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
    avg_price: Decimal | None = None
    current_price: Decimal | None = None
    current_value: Decimal | None = None
    cash_pnl: Decimal | None = None
    percent_pnl: Decimal | None = None
    title: str | None = None
    outcome: str | None = None
    slug: str | None = None


class GetPositionsResponse(BaseModel):
    account_name: str
    positions: list[PositionResponse]


class UpdateAccountValueResponse(BaseModel):
    account_id: uuid.UUID
    account_name: str
    total_value: Decimal


async def get_market_price_for_token(token_id: str) -> Decimal | None:
    """
    Get the current market price for a token using the Polymarket CLOB API.
    Uses BUY side to get the price we could sell at (bid price).
    
    See: https://docs.polymarket.com/api-reference/pricing/get-market-price
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{POLYMARKET_CLOB_URL}/price",
                params={"token_id": token_id, "side": "BUY"},
            )
            if response.status_code == 200:
                data = response.json()
                return Decimal(data["price"])
    except Exception:
        pass
    return None


async def get_batch_market_prices_for_tokens(token_ids: list[str]) -> dict[str, Decimal]:
    """
    Get market prices for multiple tokens in a single API call.
    Uses BUY side to get the price we could sell at (bid price).
    
    Returns a dict mapping token_id to price.
    """
    if not token_ids:
        return {}

    # Build request payload - request BUY side for each token
    payload = [{"token_id": token_id, "side": "BUY"} for token_id in token_ids]

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{POLYMARKET_CLOB_URL}/prices",
                json=payload,
            )
            if response.status_code == 200:
                data = response.json()
                # Extract BUY price for each token
                return {
                    token_id: Decimal(prices.get("BUY", "0"))
                    for token_id, prices in data.items()
                    if prices.get("BUY")
                }
    except Exception:
        pass
    return {}


async def get_market_metadata(token_id: str) -> dict | None:
    """
    Get market metadata (title, outcome, slug) for a token by querying Gamma API.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Query markets with clob_token_ids filter
            response = await client.get(
                f"{POLYMARKET_GAMMA_URL}/markets",
                params={"clob_token_ids": token_id},
            )
            if response.status_code == 200:
                markets = response.json()
                if markets and len(markets) > 0:
                    market = markets[0]
                    
                    # Parse token_ids to find which outcome this token corresponds to
                    token_ids = market.get("clobTokenIds", "[]")
                    if isinstance(token_ids, str):
                        token_ids = json.loads(token_ids)
                    
                    outcomes = market.get("outcomes", "[]")
                    if isinstance(outcomes, str):
                        outcomes = json.loads(outcomes)
                    
                    # Find the outcome for this token_id
                    outcome = None
                    for i, tid in enumerate(token_ids):
                        if tid == token_id:
                            outcome = outcomes[i] if i < len(outcomes) else None
                            break
                    
                    return {
                        "title": market.get("question"),
                        "outcome": outcome,
                        "slug": market.get("slug"),
                    }
    except Exception:
        pass
    return None


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
    """Get all positions held by an account with enriched market data."""
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

    # Enrich each position with market data
    enriched_positions = []
    for position in positions:
        # Calculate avg_price
        avg_price = (
            position.total_cost / position.shares
            if position.shares > 0
            else Decimal("0")
        )
        
        # Fetch current market price
        current_price = await get_market_price_for_token(position.token_id)
        
        # Calculate current_value and PnL if we have current price
        current_value = None
        cash_pnl = None
        percent_pnl = None
        if current_price is not None and position.shares > 0:
            current_value = current_price * position.shares
            cash_pnl = current_value - position.total_cost
            if position.total_cost > 0:
                percent_pnl = (cash_pnl / position.total_cost) * 100
        
        # Fetch market metadata (title, outcome, slug)
        metadata = await get_market_metadata(position.token_id)
        title = metadata.get("title") if metadata else None
        outcome = metadata.get("outcome") if metadata else None
        slug = metadata.get("slug") if metadata else None

        enriched_positions.append(
            PositionResponse(
                token_id=position.token_id,
                shares=position.shares,
                total_cost=position.total_cost,
                avg_price=avg_price,
                current_price=current_price,
                current_value=current_value,
                cash_pnl=cash_pnl,
                percent_pnl=percent_pnl,
                title=title,
                outcome=outcome,
                slug=slug,
            )
        )

    return GetPositionsResponse(
        account_name=account_name,
        positions=enriched_positions,
    )


async def update_account_value_handler(
    account_id: uuid.UUID, db: AsyncSession
) -> UpdateAccountValueResponse:
    """Calculate and store the total account value (positions + cash)."""
    try:
        # Get the account by id
        stmt = select(Account).where(Account.account_id == account_id)
        result = await db.execute(stmt)
        account = result.scalar_one_or_none()

        if not account:
            raise HTTPException(
                status_code=404,
                detail=f"Account with id '{account_id}' not found"
            )

        # Get all positions for this account
        stmt = select(Position).where(Position.account_id == account_id)
        result = await db.execute(stmt)
        positions = result.scalars().all()

        # Collect token IDs for positions with shares > 0
        token_ids = [p.token_id for p in positions if p.shares > 0]

        # Fetch all prices in one batch call
        prices = await get_batch_market_prices_for_tokens(token_ids)

        # Calculate total position value
        total_position_value = Decimal("0.00")
        for position in positions:
            if position.shares > 0:
                current_price = prices.get(position.token_id)
                if current_price is not None:
                    total_position_value += current_price * position.shares

        # Total value = cash + positions
        total_value = account.balance + total_position_value

        # Insert new AccountValue record
        account_value = AccountValue(
            account_id=account.account_id,
            account_name=account.account_name,
            total_value=total_value,
        )
        db.add(account_value)
        await db.commit()

        return UpdateAccountValueResponse(
            account_id=account.account_id,
            account_name=account.account_name,
            total_value=total_value,
        )

    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Failed to update account value: {str(e)}"
        )

