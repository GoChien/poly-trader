import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.account import Base


class Position(Base):
    __tablename__ = "positions"

    token_id: Mapped[str] = mapped_column(
        String(255), primary_key=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.account_id"), primary_key=True
    )
    shares: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_cost: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=2), nullable=False, default=Decimal("0.00")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

