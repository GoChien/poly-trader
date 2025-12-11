import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .account import Base


class KalshiAccount(Base):
    __tablename__ = "kalshi_accounts"

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    account_name: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    key_id: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    secret_name: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    is_demo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

