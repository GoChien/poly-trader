from typing import Optional, Dict
from datetime import datetime
from sqlalchemy import String, Integer, BigInteger, Float, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from models.account import Base


class KalshiMarket(Base):
    """SQLAlchemy model for Kalshi market data."""
    
    __tablename__ = "markets"
    
    # Primary key
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    
    # Market identifiers
    ticker: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    event_ticker: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    
    # Market details
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    subtitle: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    
    # Trading metrics
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    volume_24h: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    liquidity: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    
    # Price data (in dollars)
    yes_bid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    yes_ask: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    no_bid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    no_ask: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    yes_bid_dollars: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    yes_ask_dollars: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    no_bid_dollars: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    no_ask_dollars: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    last_price: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    
    # Other metrics
    open_interest: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    close_time: Mapped[str] = mapped_column(String(100), nullable=False)
    
    # Metadata (only used when persisting to database)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.utcnow, nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=True)

    @classmethod
    def from_dict(cls, data: Dict) -> 'KalshiMarket':
        """Create a Market instance from API response data."""
        market = cls(
            ticker=data.get('ticker', ''),
            event_ticker=data.get('event_ticker', ''),
            title=data.get('title', ''),
            subtitle=data.get('subtitle', ''),
            status=data.get('status', ''),
            volume=data.get('volume', 0),
            volume_24h=data.get('volume_24h', 0),
            liquidity=data.get('liquidity', 0),
            yes_bid=data.get('yes_bid', 0),
            yes_ask=data.get('yes_ask', 0),
            no_bid=data.get('no_bid', 0),
            no_ask=data.get('no_ask', 0),
            yes_bid_dollars=float(data.get('yes_bid_dollars', 0)),
            yes_ask_dollars=float(data.get('yes_ask_dollars', 0)),
            no_bid_dollars=float(data.get('no_bid_dollars', 0)),
            no_ask_dollars=float(data.get('no_ask_dollars', 0)),
            last_price=data.get('last_price', 0),
            open_interest=data.get('open_interest', 0),
            close_time=data.get('close_time', ''),
        )
        # Don't set timestamps for API-sourced data
        return market