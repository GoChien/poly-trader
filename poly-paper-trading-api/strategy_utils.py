import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.account import Account
from models.strategy import Strategy


class CreateStrategyRequest(BaseModel):
    strategy_id: str
    account_id: uuid.UUID
    token_id: str
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
    account_id: uuid.UUID
    token_id: str
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
    account_id: uuid.UUID
    token_id: str
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


async def create_strategy_handler(
    request: CreateStrategyRequest, db: AsyncSession
) -> CreateStrategyResponse:
    """Create a new trading strategy."""
    try:
        # Check if strategy with this ID already exists
        stmt = select(Strategy).where(Strategy.strategy_id == request.strategy_id)
        result = await db.execute(stmt)
        existing_strategy = result.scalar_one_or_none()

        if existing_strategy:
            raise HTTPException(
                status_code=409,
                detail=f"Strategy with id '{request.strategy_id}' already exists"
            )

        # Verify the account exists
        stmt = select(Account).where(Account.account_id == request.account_id)
        result = await db.execute(stmt)
        account = result.scalar_one_or_none()

        if not account:
            raise HTTPException(
                status_code=404,
                detail=f"Account with id '{request.account_id}' not found"
            )

        # Create new strategy
        strategy = Strategy(
            strategy_id=request.strategy_id,
            account_id=request.account_id,
            token_id=request.token_id,
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
            account_id=strategy.account_id,
            token_id=strategy.token_id,
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
                Strategy.account_id == account.account_id,
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
                    account_id=s.account_id,
                    token_id=s.token_id,
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

