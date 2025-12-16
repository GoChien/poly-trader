import asyncio
import math
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

import database
from kalshi_utils import create_kalshi_order, fetch_market_data_for_tickers
from models.account import Account
from models.order import KalshiOrder, KalshiOrderStatus, KalshiOrderAction, KalshiOrderSide
from models.position import KalshiPosition
from models.strategy import Strategy, StrategySide


def _convert_market_data_to_decimals(raw_market_data: dict) -> dict:
    """
    Convert raw Kalshi market data (with prices in cents) to Decimal dollars.
    
    Args:
        raw_market_data: Raw market data from Kalshi API with integer cent prices
        
    Returns:
        Dictionary with prices converted to Decimal dollars and other fields preserved
    """
    # Use dollar fields directly from API if available, otherwise convert cents to dollars
    yes_bid_dollars = raw_market_data.get('yes_bid_dollars')
    yes_ask_dollars = raw_market_data.get('yes_ask_dollars')
    no_bid_dollars = raw_market_data.get('no_bid_dollars')
    no_ask_dollars = raw_market_data.get('no_ask_dollars')
    
    return {
        'yes_bid': Decimal(str(yes_bid_dollars)) if yes_bid_dollars is not None else None,
        'yes_ask': Decimal(str(yes_ask_dollars)) if yes_ask_dollars is not None else None,
        'no_bid': Decimal(str(no_bid_dollars)) if no_bid_dollars is not None else None,
        'no_ask': Decimal(str(no_ask_dollars)) if no_ask_dollars is not None else None,
        'status': raw_market_data.get('status'),
        'close_time': raw_market_data.get('close_time'),
        'expected_expiration_time': raw_market_data.get('expected_expiration_time'),
    }


class CreateStrategyRequest(BaseModel):
    account_name: str
    ticker: str
    side: StrategySide
    thesis: str
    thesis_probability: Decimal
    entry_max_price: Decimal
    entry_min_implied_edge: Decimal
    entry_max_capital_risk: Decimal
    entry_max_position_shares: int
    exit_take_profit_price: Decimal
    exit_stop_loss_price: Decimal
    exit_time_stop_utc: Optional[datetime] = None
    valid_until_utc: Optional[datetime] = None
    notes: Optional[str] = None


class CreateStrategyResponse(BaseModel):
    strategy_id: str
    account_name: str
    ticker: str
    side: StrategySide
    thesis: str
    thesis_probability: Decimal
    entry_max_price: Decimal
    entry_min_implied_edge: Decimal
    entry_max_capital_risk: Decimal
    entry_max_position_shares: int
    exit_take_profit_price: Decimal
    exit_stop_loss_price: Decimal
    exit_time_stop_utc: Optional[datetime] = None
    valid_until_utc: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime


class StrategyResponse(BaseModel):
    strategy_id: str
    account_name: str
    ticker: str
    side: StrategySide
    thesis: str
    thesis_probability: Decimal
    entry_max_price: Decimal
    entry_min_implied_edge: Decimal
    entry_max_capital_risk: Decimal
    entry_max_position_shares: int
    exit_take_profit_price: Decimal
    exit_stop_loss_price: Decimal
    exit_time_stop_utc: Optional[datetime] = None
    valid_until_utc: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class StrategyWithMarketDataResponse(BaseModel):
    strategy_id: str
    account_name: str
    ticker: str
    side: StrategySide
    thesis: str
    thesis_probability: Decimal
    entry_max_price: Decimal
    entry_min_implied_edge: Decimal
    entry_max_capital_risk: Decimal
    entry_max_position_shares: int
    exit_take_profit_price: Decimal
    exit_stop_loss_price: Decimal
    exit_time_stop_utc: Optional[datetime] = None
    valid_until_utc: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    # Market data fields
    current_yes_bid: Optional[Decimal] = None
    current_yes_ask: Optional[Decimal] = None
    current_no_bid: Optional[Decimal] = None
    current_no_ask: Optional[Decimal] = None
    market_status: Optional[str] = None
    market_close_time: Optional[datetime] = None
    market_expected_expiration_time: Optional[datetime] = None
    # Calculated fields
    current_edge: Optional[Decimal] = None  # thesis_probability - current_yes_ask


class GetActiveStrategiesResponse(BaseModel):
    account_name: str
    strategies: list[StrategyWithMarketDataResponse]


class UpdateStrategyRequest(BaseModel):
    strategy_id: str  # ID of the strategy to update
    thesis: Optional[str] = None
    thesis_probability: Optional[Decimal] = None
    entry_max_price: Optional[Decimal] = None
    exit_take_profit_price: Optional[Decimal] = None
    exit_stop_loss_price: Optional[Decimal] = None
    exit_time_stop_utc: Optional[datetime] = None
    valid_until_utc: Optional[datetime] = None
    notes: Optional[str] = None


class UpdateStrategyResponse(BaseModel):
    old_strategy_id: str
    new_strategy: StrategyResponse


class RemoveStrategyResponse(BaseModel):
    success: bool
    strategy_id: str
    message: str


async def create_strategy_handler(
    request: CreateStrategyRequest, db: AsyncSession
) -> CreateStrategyResponse:
    """Create a new trading strategy."""
    try:
        # Verify the account exists
        stmt = select(Account).where(Account.account_name == request.account_name)
        result = await db.execute(stmt)
        account = result.scalar_one_or_none()

        if not account:
            raise HTTPException(
                status_code=404,
                detail=f"Account with name '{request.account_name}' not found"
            )

        # Check if there's already an active strategy for this account and ticker
        now = datetime.now(timezone.utc)
        stmt = select(Strategy).where(
            Strategy.account_name == request.account_name,
            Strategy.ticker == request.ticker,
            or_(
                Strategy.valid_until_utc > now,
                Strategy.valid_until_utc.is_(None),
            ),
        )
        result = await db.execute(stmt)
        existing_strategy = result.scalar_one_or_none()

        if existing_strategy:
            raise HTTPException(
                status_code=409,
                detail=f"Account already has an active strategy for ticker '{request.ticker}'"
            )

        # Generate strategy ID
        strategy_id = str(uuid.uuid4())

        # Create new strategy
        strategy = Strategy(
            strategy_id=strategy_id,
            account_name=request.account_name,
            ticker=request.ticker,
            side=request.side,
            thesis=request.thesis,
            thesis_probability=request.thesis_probability,
            entry_max_price=request.entry_max_price,
            entry_min_implied_edge=request.entry_min_implied_edge,
            entry_max_capital_risk=request.entry_max_capital_risk,
            entry_max_position_shares=request.entry_max_position_shares,
            exit_take_profit_price=request.exit_take_profit_price,
            exit_stop_loss_price=request.exit_stop_loss_price,
            exit_time_stop_utc=request.exit_time_stop_utc,
            valid_until_utc=request.valid_until_utc,
            notes=request.notes,
        )
        db.add(strategy)
        await db.commit()
        await db.refresh(strategy)

        return CreateStrategyResponse(
            strategy_id=strategy.strategy_id,
            account_name=strategy.account_name,
            ticker=strategy.ticker,
            side=strategy.side,
            thesis=strategy.thesis,
            thesis_probability=strategy.thesis_probability,
            entry_max_price=strategy.entry_max_price,
            entry_min_implied_edge=strategy.entry_min_implied_edge,
            entry_max_capital_risk=strategy.entry_max_capital_risk,
            entry_max_position_shares=strategy.entry_max_position_shares,
            exit_take_profit_price=strategy.exit_take_profit_price,
            exit_stop_loss_price=strategy.exit_stop_loss_price,
            exit_time_stop_utc=strategy.exit_time_stop_utc,
            valid_until_utc=strategy.valid_until_utc,
            notes=strategy.notes,
            created_at=strategy.created_at,
        )

    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Failed to create strategy: {str(e)}"
        )


async def get_active_strategies_handler(
    account_name: str, db: AsyncSession
) -> GetActiveStrategiesResponse:
    """Get all active strategies for an account with current market data."""
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

        # Get active strategies (valid_until_utc > now OR valid_until_utc is null)
        now = datetime.now(timezone.utc)
        stmt = (
            select(Strategy)
            .where(
                Strategy.account_name == account_name,
                or_(
                    Strategy.valid_until_utc > now,
                    Strategy.valid_until_utc.is_(None),
                ),
            )
            .order_by(Strategy.created_at.desc())
        )
        result = await db.execute(stmt)
        strategies = result.scalars().all()

        if not strategies:
            return GetActiveStrategiesResponse(
                account_name=account_name,
                strategies=[]
            )

        # Fetch market data for all tickers
        tickers = [s.ticker for s in strategies]
        raw_market_data_map = await fetch_market_data_for_tickers(tickers)

        # Build response with market data
        strategies_with_market_data = []
        for s in strategies:
            raw_market_data = raw_market_data_map.get(s.ticker, {})
            market_data = _convert_market_data_to_decimals(raw_market_data) if raw_market_data else {}
            
            # Extract market data fields
            yes_ask = market_data.get('yes_ask')
            yes_bid = market_data.get('yes_bid')
            no_ask = market_data.get('no_ask')
            no_bid = market_data.get('no_bid')
            
            # Calculate current edge if we have yes_ask
            current_edge = None
            if yes_ask is not None:
                current_edge = s.thesis_probability - yes_ask
            
            strategies_with_market_data.append(
                StrategyWithMarketDataResponse(
                    strategy_id=s.strategy_id,
                    account_name=s.account_name,
                    ticker=s.ticker,
                    side=s.side,
                    thesis=s.thesis,
                    thesis_probability=s.thesis_probability,
                    entry_max_price=s.entry_max_price,
                    entry_min_implied_edge=s.entry_min_implied_edge,
                    entry_max_capital_risk=s.entry_max_capital_risk,
                    entry_max_position_shares=s.entry_max_position_shares,
                    exit_take_profit_price=s.exit_take_profit_price,
                    exit_stop_loss_price=s.exit_stop_loss_price,
                    exit_time_stop_utc=s.exit_time_stop_utc,
                    valid_until_utc=s.valid_until_utc,
                    notes=s.notes,
                    created_at=s.created_at,
                    updated_at=s.updated_at,
                    # Market data
                    current_yes_bid=yes_bid,
                    current_yes_ask=yes_ask,
                    current_no_bid=no_bid,
                    current_no_ask=no_ask,
                    market_status=market_data.get('status'),
                    market_close_time=market_data.get('close_time'),
                    market_expected_expiration_time=market_data.get('expected_expiration_time'),
                    # Calculated fields
                    current_edge=current_edge,
                )
            )

        return GetActiveStrategiesResponse(
            account_name=account_name,
            strategies=strategies_with_market_data
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get active strategies: {str(e)}"
        )


async def update_strategy_handler(
    request: UpdateStrategyRequest, db: AsyncSession
) -> UpdateStrategyResponse:
    """
    Update a strategy by expiring the old one and creating a new version.
    
    This implements an immutable update pattern:
    1. Find the existing strategy
    2. Set its valid_until_utc to now (expire it)
    3. Create a new strategy with updated values and a new ID
    """
    try:
        # Find the existing strategy
        stmt = select(Strategy).where(Strategy.strategy_id == request.strategy_id)
        result = await db.execute(stmt)
        old_strategy = result.scalar_one_or_none()

        if not old_strategy:
            raise HTTPException(
                status_code=404,
                detail=f"Strategy with id '{request.strategy_id}' not found"
            )

        now = datetime.now(timezone.utc)

        # Check if strategy is already expired
        if old_strategy.valid_until_utc and old_strategy.valid_until_utc <= now:
            raise HTTPException(
                status_code=400,
                detail=f"Strategy '{request.strategy_id}' is already expired"
            )

        # Expire the old strategy
        old_strategy.valid_until_utc = now

        # Generate new strategy ID
        new_strategy_id = str(uuid.uuid4())

        # Create new strategy with updated values (use old values as defaults)
        new_strategy = Strategy(
            strategy_id=new_strategy_id,
            account_name=old_strategy.account_name,
            ticker=old_strategy.ticker,
            side=old_strategy.side,
            thesis=request.thesis if request.thesis is not None else old_strategy.thesis,
            thesis_probability=(
                request.thesis_probability
                if request.thesis_probability is not None
                else old_strategy.thesis_probability
            ),
            entry_max_price=(
                request.entry_max_price
                if request.entry_max_price is not None
                else old_strategy.entry_max_price
            ),
            entry_min_implied_edge=old_strategy.entry_min_implied_edge,
            entry_max_capital_risk=old_strategy.entry_max_capital_risk,
            entry_max_position_shares=old_strategy.entry_max_position_shares,
            exit_take_profit_price=(
                request.exit_take_profit_price
                if request.exit_take_profit_price is not None
                else old_strategy.exit_take_profit_price
            ),
            exit_stop_loss_price=(
                request.exit_stop_loss_price
                if request.exit_stop_loss_price is not None
                else old_strategy.exit_stop_loss_price
            ),
            exit_time_stop_utc=(
                request.exit_time_stop_utc
                if request.exit_time_stop_utc is not None
                else old_strategy.exit_time_stop_utc
            ),
            valid_until_utc=(
                request.valid_until_utc
                if request.valid_until_utc is not None
                else None  # New strategy starts without expiration unless specified
            ),
            notes=request.notes if request.notes is not None else old_strategy.notes,
        )

        db.add(new_strategy)
        await db.commit()
        await db.refresh(new_strategy)

        return UpdateStrategyResponse(
            old_strategy_id=request.strategy_id,
            new_strategy=StrategyResponse(
                strategy_id=new_strategy.strategy_id,
                account_name=new_strategy.account_name,
                ticker=new_strategy.ticker,
                side=new_strategy.side,
                thesis=new_strategy.thesis,
                thesis_probability=new_strategy.thesis_probability,
                entry_max_price=new_strategy.entry_max_price,
                entry_min_implied_edge=new_strategy.entry_min_implied_edge,
                entry_max_capital_risk=new_strategy.entry_max_capital_risk,
                entry_max_position_shares=new_strategy.entry_max_position_shares,
                exit_take_profit_price=new_strategy.exit_take_profit_price,
                exit_stop_loss_price=new_strategy.exit_stop_loss_price,
                exit_time_stop_utc=new_strategy.exit_time_stop_utc,
                valid_until_utc=new_strategy.valid_until_utc,
                notes=new_strategy.notes,
                created_at=new_strategy.created_at,
                updated_at=new_strategy.updated_at,
            ),
        )

    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Failed to update strategy: {str(e)}"
        )


async def remove_strategy_handler(
    strategy_id: str, db: AsyncSession
) -> RemoveStrategyResponse:
    """
    Remove (expire) a strategy by setting its valid_until_utc to now.
    
    This effectively deactivates the strategy so it will no longer execute trades.
    The strategy is not deleted from the database, just expired.
    
    If the strategy has an open position, a market sell order is automatically placed
    to close the position at the current market price.
    """
    try:
        # Find the existing strategy
        stmt = select(Strategy).where(Strategy.strategy_id == strategy_id)
        result = await db.execute(stmt)
        strategy = result.scalar_one_or_none()

        if not strategy:
            raise HTTPException(
                status_code=404,
                detail=f"Strategy with id '{strategy_id}' not found"
            )

        now = datetime.now(timezone.utc)

        # Check if strategy is already expired
        if strategy.valid_until_utc and strategy.valid_until_utc <= now:
            raise HTTPException(
                status_code=400,
                detail=f"Strategy '{strategy_id}' is already expired"
            )

        # Expire the strategy
        strategy.valid_until_utc = now
        await db.commit()

        # At the same time, sell all the positions related to this strategy at market price.
        # First, get the account
        account_stmt = select(Account).where(Account.account_name == strategy.account_name)
        account_result = await db.execute(account_stmt)
        account = account_result.scalar_one_or_none()
        
        order_id = None
        if account:
            # Check if there's a position for this ticker
            position_stmt = select(KalshiPosition).where(
                KalshiPosition.account_id == account.account_id,
                KalshiPosition.ticker == strategy.ticker
            )
            position_result = await db.execute(position_stmt)
            position = position_result.scalar_one_or_none()
            
            # If position exists and is non-zero, place a market sell order to close it
            if position and position.position != 0:
                # Determine side and count based on position
                # Positive position = yes side, negative position = no side
                if position.position > 0:
                    side = "yes"
                    count = position.position
                else:
                    side = "no"
                    count = abs(position.position)
                
                # Place market sell order to close the position
                order_response = await create_kalshi_order(
                    db=db,
                    account_name=strategy.account_name,
                    ticker=strategy.ticker,
                    side=side,
                    action="sell",
                    count=count,
                    type="market",
                )
                order_id = order_response.get('order_id')

        message = f"Strategy for {strategy.ticker} has been successfully removed (expired)"
        if order_id:
            message += f". Market sell order placed to close position (order_id: {order_id})"
        
        return RemoveStrategyResponse(
            success=True,
            strategy_id=strategy.strategy_id,
            message=message
        )

    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Failed to remove strategy: {str(e)}"
        )


class ProcessStrategyResult(BaseModel):
    strategy_id: str
    ticker: str
    action: str  # "buy", "sell_take_profit", "sell_stop_loss", "hold", "skip"
    reason: str
    order_size: Optional[int] = None
    order_price: Optional[Decimal] = None
    current_bid_price: Optional[Decimal] = None
    current_ask_price: Optional[Decimal] = None
    order_id: Optional[str] = None


async def process_strategy_handler(
    strategy: Strategy, db: AsyncSession,
    market_data_map: dict[str, dict]
) -> ProcessStrategyResult:
    """
    Process a single trading strategy and execute trades based on entry/exit rules.
    
    Entry rules (when no position exists):
    1. If current ask price > entry_max_price: skip
    2. Calculate edge = thesis_probability - current_ask_price
    3. If edge < entry_min_implied_edge: skip
    4. Calculate size = min(floor(max_capital_risk / ask_price), max_position_shares)
    5. Place buy order
    
    Exit rules (when position exists):
    1. If current bid price >= exit_take_profit_price: sell (take profit)
    2. If current bid price <= exit_stop_loss_price: sell (stop loss)
    3. Otherwise: hold
    
    Args:
        strategy: Strategy to process
        db: Database session
        market_data_map: Dictionary mapping ticker -> market data (prices, status, etc.)
    """
    try:
        # 1. Get market data from the pre-fetched map
        market_data = market_data_map.get(strategy.ticker)
        
        if not market_data:
            raise HTTPException(
                status_code=404,
                detail=f"Market data not found for ticker '{strategy.ticker}'"
            )
        
        if strategy.side == StrategySide.YES:
            ask_price = market_data['yes_ask']
            bid_price = market_data['yes_bid']
        else:
            ask_price = market_data['no_ask']
            bid_price = market_data['no_bid']

        if ask_price is None or bid_price is None:
            raise HTTPException(
                status_code=400,
                detail=f"Market prices not available for ticker '{strategy.ticker}' for side {strategy.side}"
            )

        # 2. Get existing position for this ticker from database
        # First get the account_id
        account_stmt = select(Account).where(Account.account_name == strategy.account_name)
        account_result = await db.execute(account_stmt)
        account = account_result.scalar_one_or_none()
        
        if not account:
            raise HTTPException(
                status_code=404,
                detail=f"Account '{strategy.account_name}' not found"
            )
        
        # Query KalshiPosition table
        position_stmt = select(KalshiPosition).where(
            KalshiPosition.account_id == account.account_id,
            KalshiPosition.ticker == strategy.ticker
        )
        position_result = await db.execute(position_stmt)
        kalshi_position = position_result.scalar_one_or_none()
        
        position_size = kalshi_position.position if kalshi_position else 0
        position_side = StrategySide.YES if position_size >= 0 else StrategySide.NO
        
        # 3. If already have a position, check exit rules first
        if position_size != 0:

            if position_side != strategy.side:
                raise HTTPException(
                    status_code=400,
                    detail=f"Position side {position_side} does not match strategy side {strategy.side}"
                )

            # Check take profit
            if bid_price >= strategy.exit_take_profit_price:
                # Place sell order for all shares at bid price using Kalshi API
                # Convert price from dollars to cents for Kalshi API
                price_cents = int(round(float(bid_price) * 100))
                
                # Determine which price field to use based on strategy side
                yes_price = price_cents if strategy.side == StrategySide.YES else None
                no_price = price_cents if strategy.side == StrategySide.NO else None
                
                order_response = await create_kalshi_order(
                    db=db,
                    account_name=strategy.account_name,
                    ticker=strategy.ticker,
                    side=strategy.side.value,  # "yes" or "no"
                    action="sell",
                    count=abs(position_size),  # Use absolute value for count
                    yes_price=yes_price,
                    no_price=no_price,
                    type="limit",
                )
                
                return ProcessStrategyResult(
                    strategy_id=strategy.strategy_id,
                    ticker=strategy.ticker,
                    action="sell_take_profit",
                    reason=f"Take profit triggered: bid price {bid_price} >= target {strategy.exit_take_profit_price}",
                    order_size=abs(position_size),
                    order_price=bid_price,
                    current_bid_price=bid_price,
                    current_ask_price=ask_price,
                    order_id=order_response.get('order', {}).get('order_id') or order_response.get('order_id'),
                )
            
            # Check stop loss
            if bid_price <= strategy.exit_stop_loss_price:
                # Place market sell order to exit immediately at current market price
                # No price specification needed for market orders
                order_response = await create_kalshi_order(
                    db=db,
                    account_name=strategy.account_name,
                    ticker=strategy.ticker,
                    side=strategy.side.value,  # "yes" or "no"
                    action="sell",
                    count=abs(position_size),  # Use absolute value for count
                    type="market",  # Market order for immediate execution at market price
                )
                
                # Expire the strategy after stop loss is triggered
                # Reload the strategy in the current session to ensure changes are persisted
                strategy_stmt = select(Strategy).where(Strategy.strategy_id == strategy.strategy_id)
                strategy_result = await db.execute(strategy_stmt)
                strategy_to_expire = strategy_result.scalar_one()
                
                now = datetime.now(timezone.utc)
                strategy_to_expire.valid_until_utc = now
                await db.commit()
                
                return ProcessStrategyResult(
                    strategy_id=strategy.strategy_id,
                    ticker=strategy.ticker,
                    action="sell_stop_loss",
                    reason=f"Stop loss triggered: bid price {bid_price} <= stop loss {strategy.exit_stop_loss_price}. Strategy expired.",
                    order_size=abs(position_size),
                    order_price=bid_price,
                    current_bid_price=bid_price,
                    current_ask_price=ask_price,
                    order_id=order_response.get('order', {}).get('order_id') or order_response.get('order_id'),
                )
            
            # Otherwise, keep holding
            return ProcessStrategyResult(
                strategy_id=strategy.strategy_id,
                ticker=strategy.ticker,
                action="hold",
                reason=f"Holding position: bid price {bid_price} within range (stop loss: {strategy.exit_stop_loss_price}, take profit: {strategy.exit_take_profit_price})",
                current_bid_price=bid_price,
                current_ask_price=ask_price,
            )
        
        # 4. No position, check entry rules
        # Check if current price is higher than max entry price
        if ask_price > strategy.entry_max_price:
            return ProcessStrategyResult(
                strategy_id=strategy.strategy_id,
                ticker=strategy.ticker,
                action="skip",
                reason=f"Price too high: ask price {ask_price} > max entry price {strategy.entry_max_price}",
                current_bid_price=bid_price,
                current_ask_price=ask_price,
            )
        
        # Calculate edge = thesis_probability - current_ask_price
        edge = strategy.thesis_probability - ask_price
        
        if edge < strategy.entry_min_implied_edge:
            return ProcessStrategyResult(
                strategy_id=strategy.strategy_id,
                ticker=strategy.ticker,
                action="skip",
                reason=f"Edge too low: edge {edge} < min edge {strategy.entry_min_implied_edge}",
                current_bid_price=bid_price,
                current_ask_price=ask_price,
            )
        
        # Calculate position size
        max_shares_by_risk = math.floor(strategy.entry_max_capital_risk / ask_price)
        size = min(max_shares_by_risk, strategy.entry_max_position_shares)
        
        if size <= 0:
            return ProcessStrategyResult(
                strategy_id=strategy.strategy_id,
                ticker=strategy.ticker,
                action="skip",
                reason=f"Calculated size is 0: max_capital_risk={strategy.entry_max_capital_risk}, ask_price={ask_price}",
                current_bid_price=bid_price,
                current_ask_price=ask_price,
            )
        
        # Check if there's already an open non-expired order for this strategy
        # This prevents creating duplicate orders
        current_ts = int(datetime.now(timezone.utc).timestamp())
        order_side = KalshiOrderSide.YES if strategy.side == StrategySide.YES else KalshiOrderSide.NO
        
        existing_order_stmt = select(KalshiOrder).where(
            KalshiOrder.account_id == account.account_id,
            KalshiOrder.ticker == strategy.ticker,
            KalshiOrder.side == order_side,
            KalshiOrder.action == KalshiOrderAction.BUY,
            KalshiOrder.status == KalshiOrderStatus.OPEN,
            KalshiOrder.expiration_ts > current_ts
        )
        existing_order_result = await db.execute(existing_order_stmt)
        existing_order = existing_order_result.scalar_one_or_none()
        
        if existing_order:
            return ProcessStrategyResult(
                strategy_id=strategy.strategy_id,
                ticker=strategy.ticker,
                action="skip",
                reason=f"Already have an open buy order (ID: {existing_order.order_id}) for this ticker and side",
                current_bid_price=bid_price,
                current_ask_price=ask_price,
                order_id=str(existing_order.order_id),
            )
        
        # Place buy order using Kalshi API
        # Convert price from dollars to cents for Kalshi API
        price_cents = int(round(float(ask_price) * 100))
        
        # Determine which price field to use based on strategy side
        yes_price = price_cents if strategy.side == StrategySide.YES else None
        no_price = price_cents if strategy.side == StrategySide.NO else None
        
        order_response = await create_kalshi_order(
            db=db,
            account_name=strategy.account_name,
            ticker=strategy.ticker,
            side=strategy.side.value,  # "yes" or "no"
            action="buy",
            count=size,
            yes_price=yes_price,
            no_price=no_price,
            type="limit",
        )
        
        return ProcessStrategyResult(
            strategy_id=strategy.strategy_id,
            ticker=strategy.ticker,
            action="buy",
            reason=f"Entry conditions met: edge {edge} >= min edge {strategy.entry_min_implied_edge}, price {ask_price} <= max {strategy.entry_max_price}",
            order_size=size,
            order_price=ask_price,
            current_bid_price=bid_price,
            current_ask_price=ask_price,
            order_id=order_response.get('order', {}).get('order_id') or order_response.get('order_id'),
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process strategy {strategy.strategy_id}: {str(e)}"
        )


class ProcessStrategiesResponse(BaseModel):
    account_name: str
    total_strategies: int
    results: list[ProcessStrategyResult]


async def process_strategies_handler(
    account_name: str, db: AsyncSession
) -> ProcessStrategiesResponse:
    """
    Process all active strategies for an account.
    
    1. Queries all active strategies (valid_until_utc > now or null)
    2. Processes each strategy in parallel using process_strategy_handler
    3. Returns results for all strategies
    """
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

        # Get active strategies (valid_until_utc > now OR valid_until_utc is null)
        now = datetime.now(timezone.utc)
        stmt = (
            select(Strategy)
            .where(
                Strategy.account_name == account_name,
                or_(
                    Strategy.valid_until_utc > now,
                    Strategy.valid_until_utc.is_(None),
                ),
            )
            .order_by(Strategy.created_at.desc())
        )
        result = await db.execute(stmt)
        strategies = result.scalars().all()

        if not strategies:
            return ProcessStrategiesResponse(
                account_name=account_name,
                total_strategies=0,
                results=[],
            )
        
        # Fetch market data for all tickers at once
        tickers = [strategy.ticker for strategy in strategies]
        raw_market_data_map = await fetch_market_data_for_tickers(tickers)
        
        # Convert all market data to Decimal format
        market_data_map = {
            ticker: _convert_market_data_to_decimals(raw_data)
            for ticker, raw_data in raw_market_data_map.items()
        }
        
        # Process each strategy in parallel with separate sessions
        # Each strategy gets its own session to avoid concurrent commit/rollback conflicts
        async def process_with_new_session(strategy: Strategy) -> ProcessStrategyResult:
            async with database.async_session_maker() as strategy_db:
                return await process_strategy_handler(strategy, strategy_db, market_data_map)

        tasks = [process_with_new_session(strategy) for strategy in strategies]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to error results
        processed_results: list[ProcessStrategyResult] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append(
                    ProcessStrategyResult(
                        strategy_id=strategies[i].strategy_id,
                        ticker=strategies[i].ticker,
                        action="error",
                        reason=str(result),
                    )
                )
            else:
                processed_results.append(result)

        return ProcessStrategiesResponse(
            account_name=account_name,
            total_strategies=len(strategies),
            results=processed_results,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process strategies: {str(e)}"
        )
