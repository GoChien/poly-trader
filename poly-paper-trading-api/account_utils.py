import asyncio
import json
import logging
import uuid
from datetime import datetime
from decimal import Decimal

import httpx
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.account import Account, AccountValue
from models.order import Order, OrderSide, OrderStatus
from models.position import Position
from models.transaction import Transaction

POLYMARKET_CLOB_URL = "https://clob.polymarket.com"
POLYMARKET_GAMMA_URL = "https://gamma-api.polymarket.com"

logger = logging.getLogger(__name__)


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


class AccountValueRecord(BaseModel):
    timestamp: datetime
    total_value: Decimal


class GetAccountValueHistoryResponse(BaseModel):
    account_id: uuid.UUID
    account_name: str
    start_time: datetime
    end_time: datetime
    values: list[AccountValueRecord]


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
    Returns the midpoint price (average of BUY and SELL) for better value evaluation.
    
    Returns a dict mapping token_id to midpoint price.
    """
    if not token_ids:
        return {}

    # Build request payload - request both BUY and SELL sides for each token
    payload = []
    for token_id in token_ids:
        payload.append({"token_id": token_id, "side": "BUY"})
        payload.append({"token_id": token_id, "side": "SELL"})

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{POLYMARKET_CLOB_URL}/prices",
                json=payload,
            )
            if response.status_code == 200:
                data = response.json()
                # Calculate midpoint price for each token
                result = {}
                for token_id, prices in data.items():
                    buy_price = prices.get("BUY")
                    sell_price = prices.get("SELL")
                    if buy_price and sell_price:
                        # Midpoint = (BUY + SELL) / 2
                        result[token_id] = (Decimal(buy_price) + Decimal(sell_price)) / 2
                    elif buy_price:
                        result[token_id] = Decimal(buy_price)
                    elif sell_price:
                        result[token_id] = Decimal(sell_price)
                return result
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
    # Fetch all market prices and metadata in parallel
    token_ids = [position.token_id for position in positions]
    
    # Gather all API calls in parallel
    market_prices_task = asyncio.gather(*[get_market_price_for_token(token_id) for token_id in token_ids])
    market_metadata_task = asyncio.gather(*[get_market_metadata(token_id) for token_id in token_ids])
    
    market_prices, market_metadatas = await asyncio.gather(market_prices_task, market_metadata_task)
    
    # Build enriched positions with the fetched data
    enriched_positions = []
    for position, current_price, metadata in zip(positions, market_prices, market_metadatas):
        # Calculate avg_price
        avg_price = (
            position.total_cost / position.shares
            if position.shares > 0
            else Decimal("0")
        )
        
        # Calculate current_value and PnL if we have current price
        current_value = None
        cash_pnl = None
        percent_pnl = None
        if current_price is not None and position.shares > 0:
            current_value = current_price * position.shares
            cash_pnl = current_value - position.total_cost
            if position.total_cost > 0:
                percent_pnl = (cash_pnl / position.total_cost) * 100
        
        # Extract market metadata (title, outcome, slug)
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
    """Calculate and store the total account value (positions + cash + open orders)."""
    try:
        logger.info(f"Starting account value calculation for account_id={account_id}")
        
        # Get the account by id
        stmt = select(Account).where(Account.account_id == account_id)
        result = await db.execute(stmt)
        account = result.scalar_one_or_none()

        if not account:
            raise HTTPException(
                status_code=404,
                detail=f"Account with id '{account_id}' not found"
            )

        logger.info(f"Account found: name={account.account_name}, balance={account.balance}")

        # Get all positions for this account
        stmt = select(Position).where(Position.account_id == account_id)
        result = await db.execute(stmt)
        positions = result.scalars().all()
        
        logger.info(f"Found {len(positions)} positions:")
        for pos in positions:
            logger.info(f"  - token_id={pos.token_id}, shares={pos.shares}, total_cost={pos.total_cost}")

        # Get all open orders for this account
        stmt = select(Order).where(
            Order.account_id == account_id,
            Order.status == OrderStatus.OPEN,
        )
        result = await db.execute(stmt)
        open_orders = result.scalars().all()
        
        logger.info(f"Found {len(open_orders)} open orders:")
        for order in open_orders:
            logger.info(f"  - order_id={order.order_id}, side={order.side}, token_id={order.token_id}, price={order.price}, size={order.size}")

        # Calculate reserved cash from BUY orders and reserved shares from SELL orders
        reserved_cash = Decimal("0.00")
        reserved_shares: dict[str, int] = {}  # token_id -> additional shares

        for order in open_orders:
            if order.side == OrderSide.BUY:
                # BUY orders have reserved cash (price * size)
                order_value = order.price * order.size
                reserved_cash += order_value
                logger.info(f"  BUY order reserves ${order_value} (price={order.price} * size={order.size})")
            else:
                # SELL orders have reserved shares
                reserved_shares[order.token_id] = (
                    reserved_shares.get(order.token_id, 0) + order.size
                )
                logger.info(f"  SELL order reserves {order.size} shares of {order.token_id}")

        logger.info(f"Total reserved cash from BUY orders: ${reserved_cash}")
        logger.info(f"Total reserved shares from SELL orders: {reserved_shares}")

        # Build effective shares map: current position shares + reserved shares from SELL orders
        effective_shares: dict[str, int] = {}
        for position in positions:
            effective_shares[position.token_id] = position.shares

        for token_id, shares in reserved_shares.items():
            effective_shares[token_id] = effective_shares.get(token_id, 0) + shares

        logger.info(f"Effective shares (positions + reserved SELL orders):")
        for token_id, shares in effective_shares.items():
            logger.info(f"  - {token_id}: {shares} shares")

        # Collect token IDs with shares > 0 for price fetching
        token_ids = [tid for tid, shares in effective_shares.items() if shares > 0]
        logger.info(f"Fetching prices for {len(token_ids)} tokens")

        # Fetch all prices in one batch call
        prices = await get_batch_market_prices_for_tokens(token_ids)
        logger.info(f"Fetched {len(prices)} prices:")
        for token_id, price in prices.items():
            logger.info(f"  - {token_id}: ${price}")

        # Calculate total position value (including reserved shares from SELL orders)
        total_position_value = Decimal("0.00")
        logger.info("Calculating position values:")
        for token_id, shares in effective_shares.items():
            if shares > 0:
                current_price = prices.get(token_id)
                if current_price is not None:
                    position_value = current_price * shares
                    total_position_value += position_value
                    logger.info(f"  - {token_id}: {shares} shares * ${current_price} = ${position_value}")
                else:
                    logger.warning(f"  - {token_id}: No price available for {shares} shares")

        logger.info(f"Total position value: ${total_position_value}")

        # Total value = cash + reserved cash from BUY orders + position value
        total_value = account.balance + reserved_cash + total_position_value
        
        logger.info(f"Final calculation:")
        logger.info(f"  Account balance: ${account.balance}")
        logger.info(f"  Reserved cash (BUY orders): ${reserved_cash}")
        logger.info(f"  Position value (including reserved SELL orders): ${total_position_value}")
        logger.info(f"  TOTAL ACCOUNT VALUE: ${total_value}")

        # Insert new AccountValue record
        account_value = AccountValue(
            account_id=account.account_id,
            account_name=account.account_name,
            total_value=total_value,
        )
        db.add(account_value)
        await db.commit()
        
        logger.info(f"Account value record saved successfully")

        return UpdateAccountValueResponse(
            account_id=account.account_id,
            account_name=account.account_name,
            total_value=total_value,
        )

    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        logger.error(f"Error calculating account value: {str(e)}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Failed to update account value: {str(e)}"
        )


async def get_account_value_history_handler(
    account_name: str,
    start_time: datetime,
    end_time: datetime,
    db: AsyncSession,
) -> GetAccountValueHistoryResponse:
    """Get account value history between start_time and end_time."""
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

        # Query account values within the time range
        stmt = (
            select(AccountValue)
            .where(
                AccountValue.account_id == account.account_id,
                AccountValue.timestamp >= start_time,
                AccountValue.timestamp <= end_time,
            )
            .order_by(AccountValue.timestamp)
        )
        result = await db.execute(stmt)
        account_values = result.scalars().all()

        # Convert to response format
        values = [
            AccountValueRecord(
                timestamp=av.timestamp,
                total_value=av.total_value,
            )
            for av in account_values
        ]

        return GetAccountValueHistoryResponse(
            account_id=account.account_id,
            account_name=account.account_name,
            start_time=start_time,
            end_time=end_time,
            values=values,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get account value history: {str(e)}"
        )


class PositionDiscrepancy(BaseModel):
    token_id: str
    expected_shares: int
    actual_shares: int
    difference: int
    is_correct: bool


class AuditAccountResponse(BaseModel):
    account_id: uuid.UUID
    account_name: str
    initial_balance: Decimal
    expected_balance: Decimal
    actual_balance: Decimal
    balance_difference: Decimal
    balance_is_correct: bool
    position_discrepancies: list[PositionDiscrepancy]
    all_positions_correct: bool
    is_consistent: bool


async def audit_account_handler(
    account_name: str, db: AsyncSession
) -> AuditAccountResponse:
    """
    Audit account by recalculating cash and positions from transactions.
    
    Starts with initial balance of 10000 and replays all transactions:
    - BUY: subtract (price * size) from cash, add size to position
    - SELL: add (price * size) to cash, subtract size from position
    
    Compares calculated values with actual database values.
    """
    try:
        logger.info(f"Starting account audit for account_name={account_name}")
        
        # Find the account by name
        stmt = select(Account).where(Account.account_name == account_name)
        result = await db.execute(stmt)
        account = result.scalar_one_or_none()

        if not account:
            raise HTTPException(
                status_code=404,
                detail=f"Account with name '{account_name}' not found"
            )

        logger.info(f"Account found: account_id={account.account_id}, current_balance={account.balance}")

        # Get all transactions for this account, ordered by execution time
        stmt = (
            select(Transaction)
            .where(Transaction.account_id == account.account_id)
            .order_by(Transaction.executed_at)
        )
        result = await db.execute(stmt)
        transactions = result.scalars().all()
        
        logger.info(f"Found {len(transactions)} transactions to process")

        # Get all current positions
        stmt = select(Position).where(Position.account_id == account.account_id)
        result = await db.execute(stmt)
        positions = result.scalars().all()
        actual_positions = {pos.token_id: pos.shares for pos in positions}
        
        logger.info(f"Current positions in database: {actual_positions}")

        # Initialize expected state
        INITIAL_BALANCE = Decimal("10000.00")
        expected_balance = INITIAL_BALANCE
        expected_positions: dict[str, int] = {}  # token_id -> shares

        logger.info(f"Starting with initial balance: ${INITIAL_BALANCE}")
        logger.info("Replaying transactions:")

        # Replay all transactions
        for i, txn in enumerate(transactions, 1):
            if txn.side == OrderSide.BUY:
                # BUY: subtract cash, add shares
                cost = txn.execution_price * txn.size
                expected_balance -= cost
                expected_positions[txn.token_id] = expected_positions.get(txn.token_id, 0) + txn.size
                logger.info(f"  {i}. BUY {txn.size} shares of {txn.token_id} at ${txn.execution_price} (cost: ${cost}) - Balance: ${expected_balance}")
            else:  # SELL
                # SELL: add cash, subtract shares
                revenue = txn.execution_price * txn.size
                expected_balance += revenue
                expected_positions[txn.token_id] = expected_positions.get(txn.token_id, 0) - txn.size
                logger.info(f"  {i}. SELL {txn.size} shares of {txn.token_id} at ${txn.execution_price} (revenue: ${revenue}) - Balance: ${expected_balance}")

        logger.info(f"\nExpected final state:")
        logger.info(f"  Balance: ${expected_balance}")
        logger.info(f"  Positions: {expected_positions}")
        
        logger.info(f"\nActual state in database:")
        logger.info(f"  Balance: ${account.balance}")
        logger.info(f"  Positions: {actual_positions}")

        # Compare balance
        balance_difference = account.balance - expected_balance
        balance_is_correct = balance_difference == Decimal("0")
        
        if balance_is_correct:
            logger.info(f"✓ Balance is CORRECT")
        else:
            logger.warning(f"✗ Balance MISMATCH: expected ${expected_balance}, got ${account.balance}, difference: ${balance_difference}")

        # Compare positions
        all_token_ids = set(expected_positions.keys()) | set(actual_positions.keys())
        position_discrepancies = []

        for token_id in all_token_ids:
            expected_shares = expected_positions.get(token_id, 0)
            actual_shares = actual_positions.get(token_id, 0)
            difference = actual_shares - expected_shares
            is_correct = difference == 0

            if not is_correct:
                logger.warning(f"✗ Position MISMATCH for {token_id}: expected {expected_shares} shares, got {actual_shares} shares, difference: {difference}")
            else:
                logger.info(f"✓ Position CORRECT for {token_id}: {actual_shares} shares")

            position_discrepancies.append(
                PositionDiscrepancy(
                    token_id=token_id,
                    expected_shares=expected_shares,
                    actual_shares=actual_shares,
                    difference=difference,
                    is_correct=is_correct,
                )
            )

        all_positions_correct = all(pd.is_correct for pd in position_discrepancies)
        is_consistent = balance_is_correct and all_positions_correct

        if is_consistent:
            logger.info(f"\n✓✓✓ Account is CONSISTENT ✓✓✓")
        else:
            logger.warning(f"\n✗✗✗ Account has DISCREPANCIES ✗✗✗")

        return AuditAccountResponse(
            account_id=account.account_id,
            account_name=account.account_name,
            initial_balance=INITIAL_BALANCE,
            expected_balance=expected_balance,
            actual_balance=account.balance,
            balance_difference=balance_difference,
            balance_is_correct=balance_is_correct,
            position_discrepancies=position_discrepancies,
            all_positions_correct=all_positions_correct,
            is_consistent=is_consistent,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during account audit: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to audit account: {str(e)}"
        )

