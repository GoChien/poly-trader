import uuid
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from account_utils import (
    CreateAccountRequest,
    CreateAccountResponse,
    GetAccountValueHistoryResponse,
    GetBalanceResponse,
    GetPositionsResponse,
    SetBalanceRequest,
    SetBalanceResponse,
    UpdateAccountValueResponse,
    create_account_handler,
    get_account_value_history_handler,
    get_balance_handler,
    get_positions_handler,
    set_balance_handler,
    update_account_value_handler,
)
from database import close_db, get_db, init_db
from models.account import Base
from models.strategy import Strategy  # noqa: F401 - imported for table creation
from order_utils import (
    CancelOrderResponse,
    GetOpenOrdersResponse,
    PlaceLimitOrderRequest,
    PlaceLimitOrderResponse,
    ProcessOpenOrdersResponse,
    cancel_order_handler,
    get_open_orders_handler,
    place_limit_order_handler,
    process_open_orders_handler,
)
from strategy_utils import (
    CreateStrategyRequest,
    CreateStrategyResponse,
    create_strategy_handler,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database connection in the running event loop
    engine = await init_db()
    # Create tables on startup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Cleanup on shutdown
    await close_db()


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.post("/accounts", response_model=CreateAccountResponse)
async def create_account(
    request: CreateAccountRequest, db: AsyncSession = Depends(get_db)
) -> CreateAccountResponse:
    """Create a new account with the given name."""
    return await create_account_handler(request, db)


@app.get("/accounts/balance", response_model=GetBalanceResponse)
async def get_balance(
    account_name: str, db: AsyncSession = Depends(get_db)
) -> GetBalanceResponse:
    """Get the balance of an existing account."""
    return await get_balance_handler(account_name, db)


@app.put("/accounts/balance", response_model=SetBalanceResponse)
async def set_balance(
    request: SetBalanceRequest, db: AsyncSession = Depends(get_db)
) -> SetBalanceResponse:
    """Update the balance of an existing account."""
    return await set_balance_handler(request, db)


@app.get("/accounts/positions", response_model=GetPositionsResponse)
async def get_positions(
    account_name: str, db: AsyncSession = Depends(get_db)
) -> GetPositionsResponse:
    """Get all positions held by an account."""
    return await get_positions_handler(account_name, db)


@app.post("/orders/limit", response_model=PlaceLimitOrderResponse)
async def place_limit_order(
    request: PlaceLimitOrderRequest, db: AsyncSession = Depends(get_db)
) -> PlaceLimitOrderResponse:
    """
    Place a limit order.
    
    For BUY orders:
    - Checks if there's sufficient balance
    - If limit price >= market price, fills immediately at market price
    - Otherwise, creates an open order
    
    For SELL orders:
    - Checks if there's sufficient shares in positions
    - If limit price <= market price, fills immediately at market price
    - Otherwise, creates an open order
    """
    return await place_limit_order_handler(request, db)


@app.post("/orders/{order_id}/cancel", response_model=CancelOrderResponse)
async def cancel_order(
    order_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> CancelOrderResponse:
    """
    Cancel an open order.
    
    Only orders with status OPEN can be cancelled.
    """
    return await cancel_order_handler(order_id, db)


@app.get("/orders/open", response_model=GetOpenOrdersResponse)
async def get_open_orders(
    account_name: str, db: AsyncSession = Depends(get_db)
) -> GetOpenOrdersResponse:
    """
    Get all open orders for an account.
    """
    return await get_open_orders_handler(account_name, db)


@app.post("/orders/process", response_model=ProcessOpenOrdersResponse)
async def process_open_orders(
    db: AsyncSession = Depends(get_db),
) -> ProcessOpenOrdersResponse:
    """
    Process all open orders and fill those that can be executed.
    
    For BUY orders:
    - Check the ask price from the market
    - If ask price <= limit price, fill the order at the limit price
    
    For SELL orders:
    - Check the bid price from the market
    - If bid price >= limit price, fill the order at the limit price
    """
    return await process_open_orders_handler(db)


@app.post("/accounts/{account_id}/value", response_model=UpdateAccountValueResponse)
async def update_account_value(
    account_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> UpdateAccountValueResponse:
    """
    Calculate and store the total account value.
    
    - Retrieves all positions for the account
    - Gets current market price for each position
    - Calculates total value = sum of (position shares * current price) + cash balance
    - Inserts a new record in the account_values table
    """
    return await update_account_value_handler(account_id, db)


@app.get("/accounts/value/history", response_model=GetAccountValueHistoryResponse)
async def get_account_value_history(
    account_name: str,
    start_time: datetime,
    end_time: datetime,
    db: AsyncSession = Depends(get_db),
) -> GetAccountValueHistoryResponse:
    """
    Get account value history between start_time and end_time.
    
    Returns all recorded account values within the specified time range,
    ordered by timestamp ascending.
    """
    return await get_account_value_history_handler(account_name, start_time, end_time, db)


@app.post("/strategies", response_model=CreateStrategyResponse)
async def create_strategy(
    request: CreateStrategyRequest, db: AsyncSession = Depends(get_db)
) -> CreateStrategyResponse:
    """
    Create a new trading strategy.
    
    A strategy defines entry/exit conditions for a specific market position:
    - Entry conditions: max price, min implied edge, capital risk limits
    - Exit conditions: take profit, stop loss, time stop
    - Thesis: reasoning and probability estimate
    """
    return await create_strategy_handler(request, db)

