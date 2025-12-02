import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.account import Base
from models.order import OrderSide


class Transaction(Base):
    __tablename__ = "transactions"

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.account_id"), nullable=False, index=True
    )
    token_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    execution_price: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=6), nullable=False
    )
    side: Mapped[OrderSide] = mapped_column(
        Enum(OrderSide, native_enum=False, length=10), nullable=False
    )
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

