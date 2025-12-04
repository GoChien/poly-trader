import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .account import Base


class Strategy(Base):
    __tablename__ = "strategies"

    # Primary identifier
    strategy_id: Mapped[str] = mapped_column(
        String(255), primary_key=True
    )

    # Account and token
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    token_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )

    # Thesis
    thesis: Mapped[str] = mapped_column(
        Text, nullable=False
    )
    thesis_probability: Mapped[Decimal] = mapped_column(
        Numeric(precision=5, scale=4), nullable=False  # e.g., 0.6800
    )

    # Entry conditions
    entry_max_price: Mapped[Decimal] = mapped_column(
        Numeric(precision=5, scale=4), nullable=False
    )
    entry_min_implied_edge: Mapped[Decimal] = mapped_column(
        Numeric(precision=5, scale=4), nullable=False  # thesis_prob - price >= this
    )
    entry_max_capital_risk: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=2), nullable=False  # hard $ risk per strategy
    )
    entry_max_position_shares: Mapped[int] = mapped_column(
        Integer, nullable=False
    )

    # Exit conditions
    exit_take_profit_price: Mapped[Decimal] = mapped_column(
        Numeric(precision=5, scale=4), nullable=False
    )
    exit_stop_loss_price: Mapped[Decimal] = mapped_column(
        Numeric(precision=5, scale=4), nullable=False
    )
    exit_time_stop_utc: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Validity and metadata
    valid_until_utc: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

