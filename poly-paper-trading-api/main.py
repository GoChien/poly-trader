import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, Query
from sqlalchemy.ext.asyncio import AsyncSession

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

from account_utils import (
    AuditAccountResponse,
    CreateAccountRequest,
    CreateAccountResponse,
    GetAccountValueHistoryResponse,
    GetBalanceResponse,
    GetPositionsResponse,
    SetBalanceRequest,
    SetBalanceResponse,
    UpdateAccountValueResponse,
    audit_account_handler,
    create_account_handler,
    get_account_value_history_handler,
    get_balance_handler,
    get_positions_handler,
    set_balance_handler,
    update_account_value_handler,
)
from kalshi_utils import (
    CreateKalshiAccountRequest,
    CreateKalshiAccountResponse,
    GetKalshiAccountPositionsResponse,
    GetKalshiAccountValueHistoryResponse,
    GetKalshiBalanceResponse,
    GetKalshiMarketsResponse,
    KalshiMarketResponse,
    UpdateKalshiAccountValueResponse,
    create_kalshi_account_handler,
    get_kalshi_account_balance,
    get_kalshi_account_positions,
    get_kalshi_account_value_history_handler,
    get_kalshi_markets,
    update_kalshi_account_value_handler,
)
from database import close_db, get_db, init_db
from models.account import Base
from models.kalshi_account import KalshiAccount  # noqa: F401 - imported for table creation
from models.kalshi_market import KalshiMarket  # noqa: F401 - imported for table creation
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
    GetActiveStrategiesResponse,
    ProcessStrategiesResponse,
    RemoveStrategyResponse,
    UpdateStrategyRequest,
    UpdateStrategyResponse,
    create_strategy_handler,
    get_active_strategies_handler,
    process_strategies_handler,
    remove_strategy_handler,
    update_strategy_handler,
)

# Only import monitoring if running in GCP (project ID is set)
ENABLE_MONITORING = bool(os.environ.get("GOOGLE_CLOUD_PROJECT"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database connection in the running event loop
    engine = await init_db()
    # Create tables on startup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Initialize Cloud Monitoring metrics if running in GCP
    if ENABLE_MONITORING:
        from monitoring import init_monitoring
        init_monitoring()
    
    yield
    
    # Cleanup on shutdown
    if ENABLE_MONITORING:
        from monitoring import shutdown_monitoring
        shutdown_monitoring()
    await close_db()


app = FastAPI(lifespan=lifespan)

# Add monitoring middleware (must be added before app starts)
# The middleware itself checks if monitoring is initialized before recording metrics
if ENABLE_MONITORING:
    from monitoring import MonitoringMiddleware
    app.add_middleware(MonitoringMiddleware)


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


@app.get("/strategies/active", response_model=GetActiveStrategiesResponse)
async def get_active_strategies(
    account_name: str, db: AsyncSession = Depends(get_db)
) -> GetActiveStrategiesResponse:
    """
    Get all active strategies for an account with current market data.
    
    A strategy is considered active if valid_until_utc is later than the current time,
    or if valid_until_utc is not set (null).
    
    For each strategy, this endpoint also fetches and returns:
    - Current market prices (yes_bid, yes_ask, no_bid, no_ask)
    - Market status and timing information
    - Calculated current edge (thesis_probability - current_yes_ask)
    
    This provides a complete view of each strategy's status relative to current market conditions.
    """
    return await get_active_strategies_handler(account_name, db)


@app.put("/strategies", response_model=UpdateStrategyResponse)
async def update_strategy(
    request: UpdateStrategyRequest, db: AsyncSession = Depends(get_db)
) -> UpdateStrategyResponse:
    """
    Update a strategy using an immutable update pattern.
    
    This endpoint:
    1. Finds the existing strategy by strategy_id
    2. Expires it by setting valid_until_utc to now
    3. Creates a new strategy with updated values and a new ID
    
    Updatable fields:
    - thesis, thesis_probability
    - entry_max_price
    - exit_take_profit_price, exit_stop_loss_price, exit_time_stop_utc
    - valid_until_utc, notes
    """
    return await update_strategy_handler(request, db)


@app.delete("/strategies", response_model=RemoveStrategyResponse)
async def remove_strategy(
    strategy_id: str, db: AsyncSession = Depends(get_db)
) -> RemoveStrategyResponse:
    """
    Remove (expire) a strategy by setting its valid_until_utc to now.
    
    This deactivates the strategy so it will no longer execute trades.
    The strategy is not deleted from the database, just expired for record-keeping.
    
    Args:
    - strategy_id: The ID of the strategy to remove (query parameter)
    
    Returns:
    - success: True if the strategy was successfully removed
    - strategy_id: The ID of the removed strategy
    - message: Confirmation message
    """
    return await remove_strategy_handler(strategy_id, db)


@app.post("/strategies/process", response_model=ProcessStrategiesResponse)
async def process_strategies(
    account_name: str, db: AsyncSession = Depends(get_db)
) -> ProcessStrategiesResponse:
    """
    Process all active strategies for an account.
    
    For each active strategy:
    - If there's an existing position, checks exit rules (take profit, stop loss)
    - If no position, checks entry rules and places buy orders if conditions are met
    
    Strategies are processed in parallel for efficiency.
    """
    return await process_strategies_handler(account_name, db)


@app.get("/accounts/audit", response_model=AuditAccountResponse)
async def audit_account(
    account_name: str, db: AsyncSession = Depends(get_db)
) -> AuditAccountResponse:
    """
    Audit account data integrity by recalculating cash and positions from transactions.
    
    This endpoint verifies that the account's cash balance and positions match
    what they should be based on all transactions, using transactions as the source of truth.
    
    Process:
    1. Starts with initial balance of $10,000
    2. Replays all transactions in chronological order:
       - BUY: subtract (price x size) from cash, add size to position
       - SELL: add (price x size) to cash, subtract size from position
    3. Compares calculated values with actual database values
    
    Returns:
    - Expected vs actual balance (with difference)
    - Expected vs actual positions for each token (with differences)
    - Whether the account is consistent (all values match)
    """
    return await audit_account_handler(account_name, db)


@app.post("/kalshi/accounts", response_model=CreateKalshiAccountResponse)
async def create_kalshi_account(
    request: CreateKalshiAccountRequest, db: AsyncSession = Depends(get_db)
) -> CreateKalshiAccountResponse:
    """
    Create a new Kalshi account by storing API credentials.
    
    This endpoint stores Kalshi API credentials in the database for later use:
    - account_name: Unique name to identify this Kalshi account
    - key_id: The Kalshi API key ID
    - secret_name: Name of the secret in GCP Secret Manager containing the private key
    - is_demo: Whether this is a demo account (uses demo-api.kalshi.co) or production (uses api.elections.kalshi.com)
    
    Returns:
    - The created account details including the generated account_id
    """
    return await create_kalshi_account_handler(request, db)


@app.get("/kalshi/balance", response_model=GetKalshiBalanceResponse)
async def get_kalshi_balance(
    account_name: str, db: AsyncSession = Depends(get_db)
) -> GetKalshiBalanceResponse:
    """
    Get current Kalshi account balance from the Kalshi API.
    
    This endpoint connects to the Kalshi API using credentials from the database:
    - account_name: Name of the Kalshi account to query balance for
    
    The endpoint will:
    1. Look up the Kalshi account credentials in the database
    2. Connect to the appropriate Kalshi API (demo or production based on is_demo flag)
    3. Return the current balance information
    
    Returns:
    - balance: Member's available balance in cents (amount available for trading)
    - portfolio_value: Member's portfolio value in cents (current value of all positions held)
    - updated_ts: Unix timestamp of the last update to the balance
    """
    balance_data = await get_kalshi_account_balance(db, account_name)
    return GetKalshiBalanceResponse(**balance_data)


@app.get("/kalshi/positions", response_model=GetKalshiAccountPositionsResponse)
async def get_kalshi_positions(
    account_name: str, db: AsyncSession = Depends(get_db)
) -> GetKalshiAccountPositionsResponse:
    """
    Get all positions for a Kalshi account from the database.
    
    This endpoint retrieves all positions stored in the database for a Kalshi account:
    - account_name: Name of the Kalshi account to query positions for
    
    The endpoint will:
    1. Look up the Kalshi account in the database
    2. Query all non-zero positions for that account
    3. Return simplified position information
    
    Returns:
    - positions: List of all positions with:
      - ticker: Market ticker
      - side: Position side ('yes' or 'no')
      - position: Absolute position size
    """
    positions_data = await get_kalshi_account_positions(db, account_name)
    return GetKalshiAccountPositionsResponse(**positions_data)


@app.post("/kalshi/accounts/{account_name}/value", response_model=UpdateKalshiAccountValueResponse)
async def update_kalshi_account_value(
    account_name: str, db: AsyncSession = Depends(get_db)
) -> UpdateKalshiAccountValueResponse:
    """
    Calculate and store the Kalshi account total value (balance + portfolio value).
    
    This endpoint:
    1. Retrieves the balance and portfolio value from Kalshi API
    2. Calculates total value = balance + portfolio_value
    3. Stores it in the account_values table with a timestamp
    
    - account_name: Name of the Kalshi account
    
    Returns:
    - account_id: UUID of the Kalshi account
    - account_name: Name of the account
    - total_value: Total account value in dollars (balance + portfolio value, converted from cents)
    """
    return await update_kalshi_account_value_handler(account_name, db)


@app.get("/kalshi/accounts/value/history", response_model=GetKalshiAccountValueHistoryResponse)
async def get_kalshi_account_value_history(
    account_name: str,
    start_time: datetime,
    end_time: datetime,
    db: AsyncSession = Depends(get_db),
) -> GetKalshiAccountValueHistoryResponse:
    """
    Get Kalshi account value history between start_time and end_time.
    
    Returns all recorded account values within the specified time range,
    ordered by timestamp ascending.
    
    - account_name: Name of the Kalshi account
    - start_time: Start of time range (datetime)
    - end_time: End of time range (datetime)
    
    Returns:
    - account_id: UUID of the Kalshi account
    - account_name: Name of the account
    - start_time: Start of the queried time range
    - end_time: End of the queried time range
    - values: List of account value records with timestamp and total_value
    """
    return await get_kalshi_account_value_history_handler(account_name, start_time, end_time, db)


@app.get("/kalshi/markets", response_model=GetKalshiMarketsResponse)
async def get_markets(
    exclude_tickers: list[str] = Query(default=None, description="List of ticker symbols to exclude from results"),
    db: AsyncSession = Depends(get_db)
) -> GetKalshiMarketsResponse:
    """
    Get all Kalshi markets with latest data from the Kalshi API (public endpoint), with optional filtering.
    
    This endpoint:
    1. Queries the database to get filtered market tickers (applying exclude_tickers filter)
    2. Fetches the most up-to-date market data from the Kalshi public API for those tickers
    3. Returns fresh market data to avoid database latency issues
    
    Note: This uses the public Kalshi markets endpoint which does not require authentication.
    
    Parameters:
    - exclude_tickers: Optional list of ticker symbols to exclude from the results
    
    Query parameter examples:
    - /kalshi/markets - Get all markets with latest data
    - /kalshi/markets?exclude_tickers=TICKER1&exclude_tickers=TICKER2 - Exclude specific tickers
    
    Returns:
    - markets: List of market objects with latest data from Kalshi API
    - total_count: Total number of markets returned (after filtering)
    """
    markets_data = await get_kalshi_markets(db, exclude_tickers=exclude_tickers)
    return GetKalshiMarketsResponse(
        markets=[KalshiMarketResponse(**m) for m in markets_data['markets']],
        total_count=markets_data['total_count']
    )
