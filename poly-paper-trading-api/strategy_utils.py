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
from models.kalshi_account import KalshiAccount
from models.order import OrderSide
from models.position import Position
from models.strategy import Strategy
from order_utils import get_market_price, PlaceLimitOrderRequest, place_limit_order_handler


class CreateStrategyRequest(BaseModel):
    account_name: str
    ticker: str
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


class GetActiveStrategiesResponse(BaseModel):
    account_name: str
    strategies: list[StrategyResponse]


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


async def create_strategy_handler(
    request: CreateStrategyRequest, db: AsyncSession
) -> CreateStrategyResponse:
    """Create a new trading strategy."""
    try:
        # Verify the account exists
        stmt = select(KalshiAccount).where(KalshiAccount.account_name == request.account_name)
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
    """Get all active strategies for an account (valid_until_utc > now or null)."""
    try:
        # Find the account by name
        stmt = select(KalshiAccount).where(KalshiAccount.account_name == account_name)
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

        return GetActiveStrategiesResponse(
            account_name=account_name,
            strategies=[
                StrategyResponse(
                    strategy_id=s.strategy_id,
                    account_name=s.account_name,
                    ticker=s.ticker,
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
                )
                for s in strategies
            ],
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


class ProcessStrategyResult(BaseModel):
    strategy_id: str
    ticker: str
    action: str  # "buy", "sell_take_profit", "sell_stop_loss", "hold", "skip"
    reason: str
    order_size: Optional[int] = None
    order_price: Optional[Decimal] = None
    current_bid_price: Optional[Decimal] = None
    current_ask_price: Optional[Decimal] = None


async def process_strategy_handler(
    strategy: Strategy, db: AsyncSession
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
    """
    try:
        # 1. Get market prices (both bid and ask)
        ask_price = await get_market_price(strategy.ticker, OrderSide.BUY)  # Ask price for buying
        bid_price = await get_market_price(strategy.ticker, OrderSide.SELL)  # Bid price for selling
        
        # 2. Get existing position for this ticker under this account
        # First, get the account_id from account_name
        stmt = select(KalshiAccount).where(KalshiAccount.account_name == strategy.account_name)
        result = await db.execute(stmt)
        account = result.scalar_one_or_none()
        
        if not account:
            raise HTTPException(
                status_code=404,
                detail=f"Account with name '{strategy.account_name}' not found"
            )
        
        stmt = select(Position).where(
            Position.account_id == account.account_id,
            Position.token_id == strategy.ticker,
        )
        result = await db.execute(stmt)
        position = result.scalar_one_or_none()
        
        has_position = position is not None and position.shares > 0
        
        # 3. If already have a position, check exit rules first
        if has_position:
            # Check take profit
            if bid_price >= strategy.exit_take_profit_price:
                # Place sell order for all shares at bid price
                order_request = PlaceLimitOrderRequest(
                    account_id=account.account_id,
                    price=bid_price,
                    size=position.shares,
                    side=OrderSide.SELL,
                    token_id=strategy.ticker,
                )
                await place_limit_order_handler(order_request, db)
                
                return ProcessStrategyResult(
                    strategy_id=strategy.strategy_id,
                    ticker=strategy.ticker,
                    action="sell_take_profit",
                    reason=f"Take profit triggered: bid price {bid_price} >= target {strategy.exit_take_profit_price}",
                    order_size=position.shares,
                    order_price=bid_price,
                    current_bid_price=bid_price,
                    current_ask_price=ask_price,
                )
            
            # Check stop loss
            if bid_price <= strategy.exit_stop_loss_price:
                # Place sell order for all shares at bid price
                order_request = PlaceLimitOrderRequest(
                    account_id=account.account_id,
                    price=bid_price,
                    size=position.shares,
                    side=OrderSide.SELL,
                    token_id=strategy.ticker,
                )
                await place_limit_order_handler(order_request, db)
                
                return ProcessStrategyResult(
                    strategy_id=strategy.strategy_id,
                    ticker=strategy.ticker,
                    action="sell_stop_loss",
                    reason=f"Stop loss triggered: bid price {bid_price} <= stop loss {strategy.exit_stop_loss_price}",
                    order_size=position.shares,
                    order_price=bid_price,
                    current_bid_price=bid_price,
                    current_ask_price=ask_price,
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
        
        # Place buy order
        order_request = PlaceLimitOrderRequest(
            account_id=account.account_id,
            price=ask_price,
            size=size,
            side=OrderSide.BUY,
            token_id=strategy.ticker,
        )
        await place_limit_order_handler(order_request, db)
        
        return ProcessStrategyResult(
            strategy_id=strategy.strategy_id,
            ticker=strategy.ticker,
            action="buy",
            reason=f"Entry conditions met: edge {edge} >= min edge {strategy.entry_min_implied_edge}, price {ask_price} <= max {strategy.entry_max_price}",
            order_size=size,
            order_price=ask_price,
            current_bid_price=bid_price,
            current_ask_price=ask_price,
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
        stmt = select(KalshiAccount).where(KalshiAccount.account_name == account_name)
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

        # Process each strategy in parallel with separate sessions
        # Each strategy gets its own session to avoid concurrent commit/rollback conflicts
        async def process_with_new_session(strategy: Strategy) -> ProcessStrategyResult:
            async with database.async_session_maker() as strategy_db:
                return await process_strategy_handler(strategy, strategy_db)
        
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
