import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select
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

