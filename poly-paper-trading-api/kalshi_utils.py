import os
import base64
import datetime
import uuid
from datetime import datetime as DateTime
from decimal import Decimal
from typing import Optional
import httpx
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.backends import default_backend
from cryptography.exceptions import InvalidSignature
from google.cloud import secretmanager

from models.kalshi_account import KalshiAccount
from models.kalshi_market import KalshiMarket
from models.account import Account, AccountValue
from models.position import KalshiPosition
from models.order import KalshiOrder, KalshiOrderSide, KalshiOrderAction, KalshiOrderType, KalshiOrderStatus


async def _get_kalshi_account(db: AsyncSession, account_name: str) -> KalshiAccount:
    """
    Retrieve KalshiAccount from database by account name
    
    Args:
        db: Database session
        account_name: Name of the Kalshi account
        
    Returns:
        KalshiAccount object
        
    Raises:
        ValueError: If account not found
    """
    result = await db.execute(
        select(KalshiAccount).where(KalshiAccount.account_name == account_name)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise ValueError(f"Kalshi account '{account_name}' not found")
    return account


def _get_secret_from_gcp(gcp_project_id: str, secret_name: str) -> bytes:
    """
    Retrieve secret from GCP Secret Manager
    
    Args:
        gcp_project_id: GCP project ID
        secret_name: Secret name in GCP Secret Manager
        
    Returns:
        Secret value as bytes
    """
    try:
        client = secretmanager.SecretManagerServiceClient()
        
        # Build the secret version name (using 'latest' version)
        name = f"projects/{gcp_project_id}/secrets/{secret_name}/versions/latest"
        
        # Access the secret version
        response = client.access_secret_version(request={"name": name})
        
        # Return the secret payload
        return response.payload.data
    except Exception as e:
        raise ValueError(f"Failed to retrieve secret from GCP Secret Manager: {str(e)}")


def _load_private_key(gcp_project_id: str, secret_name: str) -> rsa.RSAPrivateKey:
    """
    Load the RSA private key from GCP Secret Manager
    
    Args:
        gcp_project_id: GCP project ID
        secret_name: Secret name in GCP Secret Manager
        
    Returns:
        RSA private key
    """
    try:
        # Fetch from GCP Secret Manager
        key_bytes = _get_secret_from_gcp(gcp_project_id, secret_name)
        
        # Load the private key from bytes
        private_key = serialization.load_pem_private_key(
            key_bytes,
            password=None,
            backend=default_backend()
        )
        return private_key
    except Exception as e:
        raise ValueError(f"Failed to load private key: {str(e)}")


def _sign_message(private_key: rsa.RSAPrivateKey, message: str) -> str:
    """
    Sign a message using PSS padding with SHA256
    
    Args:
        private_key: RSA private key
        message: The message string to sign
        
    Returns:
        Base64 encoded signature
    """
    message_bytes = message.encode('utf-8')
    try:
        signature = private_key.sign(
            message_bytes,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH
            ),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode('utf-8')
    except InvalidSignature as e:
        raise ValueError("RSA sign PSS failed") from e


def _get_headers(private_key: rsa.RSAPrivateKey, api_key_id: str, method: str, path: str) -> dict:
    """
    Generate authentication headers for Kalshi API request
    
    Args:
        private_key: RSA private key
        api_key_id: Kalshi API key ID
        method: HTTP method (GET, POST, etc.)
        path: API endpoint path (without query parameters)
        
    Returns:
        Dictionary of headers
    """
    # Strip query parameters from path before signing
    path_without_query = path.split('?')[0]
    
    # Get current timestamp in milliseconds
    current_time = datetime.datetime.now()
    timestamp_ms = int(current_time.timestamp() * 1000)
    timestamp_str = str(timestamp_ms)
    
    # Create message to sign: timestamp + method + path
    message = timestamp_str + method + path_without_query
    signature = _sign_message(private_key, message)
    
    return {
        'KALSHI-ACCESS-KEY': api_key_id,
        'KALSHI-ACCESS-SIGNATURE': signature,
        'KALSHI-ACCESS-TIMESTAMP': timestamp_str
    }


async def get_kalshi_account_balance(db: AsyncSession, account_name: str) -> dict:
    """
    Get account balance from Kalshi API
    
    Args:
        db: Database session
        account_name: Name of the Kalshi account
        
    Returns:
        Dictionary containing balance information
        
    Example response:
        {
            "balance": 10000,
            "portfolio_value": 5000,
            "updated_ts": 1702500000000
        }
    """
    # Get account credentials from database
    account = await _get_kalshi_account(db, account_name)
    
    # Get GCP project ID from environment
    gcp_project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
    if not gcp_project_id:
        raise ValueError("GOOGLE_CLOUD_PROJECT environment variable must be set")
    
    # Load private key
    private_key = _load_private_key(gcp_project_id, account.secret_name)
    
    # Determine base URL based on is_demo flag
    base_url = "https://demo-api.kalshi.co" if account.is_demo else "https://api.elections.kalshi.com"
    
    # Make API request
    path = '/trade-api/v2/portfolio/balance'
    method = 'GET'
    headers = _get_headers(private_key, account.key_id, method, path)
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{base_url}{path}",
            headers=headers
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            # Log the error response body for debugging
            error_detail = response.text
            print(f"Kalshi API Error (get_kalshi_account_balance): Status {response.status_code}")
            print(f"Error detail: {error_detail}")
            print(f"Request URL: {base_url}{path}")
            print(f"Account: {account_name}, is_demo: {account.is_demo}")
            raise
        return response.json()


async def fetch_market_data_for_tickers(tickers: list[str]) -> dict[str, dict]:
    """
    Fetch current market data for a list of tickers from Kalshi API.
    
    This is a shared utility function that fetches market data from the public Kalshi API.
    It handles batching (100 tickers at a time) and error handling for each batch.
    
    Args:
        tickers: List of ticker symbols to fetch data for
        
    Returns:
        Dictionary mapping ticker to market data dict. The market data dict contains
        all raw fields from the Kalshi API response, including:
        - yes_bid, yes_ask, no_bid, no_ask (integers, in cents)
        - yes_bid_dollars, yes_ask_dollars, no_bid_dollars, no_ask_dollars (strings)
        - status, close_time, expected_expiration_time, etc.
        
    Example:
        market_data = await fetch_market_data_for_tickers(['TICKER1', 'TICKER2'])
        yes_ask_cents = market_data['TICKER1']['yes_ask']  # integer cents
    """
    if not tickers:
        return {}
    
    base_url = "https://api.elections.kalshi.com"
    path = '/trade-api/v2/markets'
    
    market_data_map = {}
    
    # Batch tickers to avoid URL length limits
    batch_size = 100
    async with httpx.AsyncClient(timeout=30.0) as client:
        for i in range(0, len(tickers), batch_size):
            batch_tickers = tickers[i:i + batch_size]
            
            try:
                params = {'tickers': ','.join(batch_tickers)}
                response = await client.get(f"{base_url}{path}", params=params)
                response.raise_for_status()
                data = response.json()
                
                # Store the complete market data for each ticker
                for market in data.get('markets', []):
                    ticker = market.get('ticker')
                    if ticker:
                        market_data_map[ticker] = market
            except Exception as e:
                # Log error but continue processing other batches
                print(f"Error fetching market data for batch {i//batch_size}: {str(e)}")
                continue
    
    return market_data_map


async def get_kalshi_account_positions(db: AsyncSession, account_name: str) -> dict:
    """
    Get all portfolio positions from the database
    
    Args:
        db: Database session
        account_name: Name of the account
        
    Returns:
        Dictionary containing:
            - positions: List of positions with ticker, side, and absolute position
    """
    # Get account from database
    stmt = select(Account).where(Account.account_name == account_name)
    result = await db.execute(stmt)
    account = result.scalar_one_or_none()
    
    if not account:
        raise HTTPException(
            status_code=404,
            detail=f"Account '{account_name}' not found"
        )
    
    # Query positions from database
    stmt = select(KalshiPosition).where(
        KalshiPosition.account_id == account.account_id,
        KalshiPosition.position != 0  # Only get non-zero positions
    )
    result = await db.execute(stmt)
    positions = result.scalars().all()
    
    # Format positions with ticker, side, and absolute position
    formatted_positions = []
    for pos in positions:
        formatted_positions.append({
            'ticker': pos.ticker,
            'side': 'yes' if pos.position > 0 else 'no',
            'position': abs(pos.position)
        })
    
    return {
        'positions': formatted_positions
    }


async def process_kalshi_orders_handler(
    account_name: str,
    db: AsyncSession,
) -> dict:
    """
    Process all non-expired open orders for a Kalshi account.
    
    For each order:
    - Checks current market price from Kalshi API
    - Determines if order can be filled (limit vs market)
    - Fills order in a single transaction:
      1. Check balance (cancel if insufficient for buy orders)
      2. Deduct balance (for buy) or check position (for sell)
      3. Update/create position
      4. Mark order as filled
    
    Args:
        account_name: Name of the Kalshi account
        db: Database session
        
    Returns:
        Dictionary containing:
            - filled_orders: List of order IDs that were filled
            - cancelled_orders: List of order IDs that were cancelled (insufficient balance)
            - total_processed: Total number of orders processed
            
    Raises:
        HTTPException: If account not found or other errors
    """
    try:
        # 1. Get the account by name
        stmt = select(Account).where(Account.account_name == account_name)
        result = await db.execute(stmt)
        account = result.scalar_one_or_none()
        
        if not account:
            raise HTTPException(
                status_code=404,
                detail=f"Account '{account_name}' not found"
            )
        
        # 2. Get all non-expired open orders for this account
        current_ts = int(DateTime.now().timestamp())
        stmt = select(KalshiOrder).where(
            KalshiOrder.account_id == account.account_id,
            KalshiOrder.status == KalshiOrderStatus.OPEN,
            KalshiOrder.expiration_ts > current_ts
        )
        result = await db.execute(stmt)
        orders = result.scalars().all()
        
        filled_orders = []
        cancelled_orders = []
        
        # 3. Get current market prices for all unique tickers
        unique_tickers = list(set(order.ticker for order in orders))
        if not unique_tickers:
            return {
                "filled_orders": [],
                "cancelled_orders": [],
                "total_processed": 0
            }
        
        # Fetch market data from Kalshi API using shared utility
        market_map = await fetch_market_data_for_tickers(unique_tickers)
        
        # 4. Process each order
        for order in orders:
            market = market_map.get(order.ticker)
            if not market:
                # Skip if market data not available
                continue
            
            # Determine if order can be filled
            can_fill = False
            fill_price_cents = None
            
            if order.type == KalshiOrderType.MARKET:
                # Market orders always fill at current market price
                can_fill = True
                # Use ask price for buys, bid price for sells
                if order.action == KalshiOrderAction.BUY:
                    fill_price_cents = market['yes_ask'] if order.side == KalshiOrderSide.YES else market['no_ask']
                else:  # SELL
                    fill_price_cents = market['yes_bid'] if order.side == KalshiOrderSide.YES else market['no_bid']
            
            elif order.type == KalshiOrderType.LIMIT:
                # Limit orders fill if market price is favorable
                if order.action == KalshiOrderAction.BUY:
                    # Buy order fills if ask price <= limit price
                    market_price = market['yes_ask'] if order.side == KalshiOrderSide.YES else market['no_ask']
                    if market_price <= order.price:
                        can_fill = True
                        fill_price_cents = market_price
                else:  # SELL
                    # Sell order fills if bid price >= limit price
                    market_price = market['yes_bid'] if order.side == KalshiOrderSide.YES else market['no_bid']
                    if market_price >= order.price:
                        can_fill = True
                        fill_price_cents = market_price
            
            if not can_fill:
                continue
            
            # 5. Fill the order in a transaction
            try:
                await _fill_kalshi_order(db, account, order, fill_price_cents)
                filled_orders.append(str(order.order_id))
            except OrderFillException as e:
                # Order cannot be filled - cancel it in a separate transaction
                order.status = KalshiOrderStatus.CANCELLED
                await db.commit()
                cancelled_orders.append(str(order.order_id))
        
        return {
            "filled_orders": filled_orders,
            "cancelled_orders": cancelled_orders,
            "total_processed": len(filled_orders) + len(cancelled_orders)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process orders: {str(e)}"
        )


class OrderFillException(Exception):
    """Exception raised when an order cannot be filled and should be cancelled"""
    pass


async def _fill_kalshi_order(
    db: AsyncSession,
    account: Account,
    order: KalshiOrder,
    fill_price_cents: int
) -> None:
    """
    Fill a single Kalshi order within a transaction.
    
    All operations are performed atomically within a single transaction:
    1. Lock and refresh account/position rows
    2. Check balance (for buy) or position (for sell)
    3. Update balance and position
    4. Mark order as filled
    
    If the order cannot be filled (insufficient balance/position), it raises
    OrderFillException and the order will be cancelled separately.
    
    Args:
        db: Database session
        account: Account object
        order: Order to fill
        fill_price_cents: Fill price in cents (1-99)
        
    Raises:
        OrderFillException: If insufficient balance or position (order should be cancelled)
    """
    # Refresh account to get latest balance with row lock (FOR UPDATE)
    stmt = select(Account).where(Account.account_id == account.account_id).with_for_update()
    result = await db.execute(stmt)
    locked_account = result.scalar_one()
    
    # Calculate cost/proceeds in dollars
    cost_or_proceeds = Decimal(fill_price_cents) / Decimal(100) * Decimal(order.count)
    
    if order.action == KalshiOrderAction.BUY:
        # Check if sufficient balance
        if locked_account.balance < cost_or_proceeds:
            raise OrderFillException(
                f"Insufficient balance for order {order.order_id}. Required: ${cost_or_proceeds}, Available: ${locked_account.balance}"
            )
        
        # Deduct balance
        locked_account.balance -= cost_or_proceeds
        
        # Update/create position
        # Positive for yes, negative for no
        position_change = order.count if order.side == KalshiOrderSide.YES else -order.count
        
        # Check if position exists (lock it)
        stmt = select(KalshiPosition).where(
            KalshiPosition.ticker == order.ticker,
            KalshiPosition.account_id == locked_account.account_id
        ).with_for_update()
        result = await db.execute(stmt)
        position = result.scalar_one_or_none()
        
        if position:
            position.position += position_change
        else:
            position = KalshiPosition(
                ticker=order.ticker,
                account_id=locked_account.account_id,
                position=position_change
            )
            db.add(position)
    
    else:  # SELL
        # Check if we have the position to sell (lock it)
        stmt = select(KalshiPosition).where(
            KalshiPosition.ticker == order.ticker,
            KalshiPosition.account_id == locked_account.account_id
        ).with_for_update()
        result = await db.execute(stmt)
        position = result.scalar_one_or_none()
        
        # Calculate required position
        # If selling yes, we need positive position >= count
        # If selling no, we need negative position <= -count (abs value >= count)
        required_position = order.count if order.side == KalshiOrderSide.YES else -order.count
        
        if not position:
            raise OrderFillException(
                f"No position to sell for order {order.order_id}"
            )
        
        # Check if we have enough position
        if order.side == KalshiOrderSide.YES and position.position < order.count:
            raise OrderFillException(
                f"Insufficient yes position for order {order.order_id}. Required: {order.count}, Available: {position.position}"
            )
        elif order.side == KalshiOrderSide.NO and position.position > -order.count:
            raise OrderFillException(
                f"Insufficient no position for order {order.order_id}. Required: {order.count}, Available: {abs(position.position)}"
            )
        
        # Update position (reduce)
        position.position -= required_position
        
        # Add proceeds to balance
        locked_account.balance += cost_or_proceeds
    
    # Mark order as filled and update price to actual fill price
    order.status = KalshiOrderStatus.FILLED
    order.price = fill_price_cents
    
    # Commit this transaction
    await db.commit()


async def create_kalshi_order(
    db: AsyncSession,
    account_name: str,
    ticker: str,
    side: str,
    action: str,
    count: int,
    expiration_ts: Optional[int] = None,
    yes_price: Optional[int] = None,
    no_price: Optional[int] = None,
    type: str = "limit",
) -> dict:
    """
    Create a paper trading order for Kalshi markets.
    
    This is the paper trading version that simulates orders without calling the Kalshi API.
    It checks account balance and creates an order record in the database.
    
    Args:
        db: Database session
        account_name: Name of the Kalshi account
        ticker: Market ticker symbol
        side: "yes" or "no" - which side to bet on
        action: "buy" or "sell"
        count: Number of contracts (must be >= 1)
        expiration_ts: Optional expiration timestamp in seconds (Unix timestamp). 
                      Defaults to 5 minutes from now.
        yes_price: Optional yes price in cents (1-99). Required for limit orders, 
                  not needed for market orders.
        no_price: Optional no price in cents (1-99). Required for limit orders,
                 not needed for market orders.
        type: Order type - "market" or "limit" (default: "limit")
              - "market": Execute at current market price (no price specification needed)
              - "limit": Execute only if price conditions are met (requires yes_price or no_price)
        
    Returns:
        Dictionary containing the created order details
            
    Raises:
        HTTPException: If account not found, insufficient balance, or invalid parameters
    """
    try:
        # 1. Get the account by name
        stmt = select(Account).where(Account.account_name == account_name)
        result = await db.execute(stmt)
        account = result.scalar_one_or_none()
        
        if not account:
            raise HTTPException(
                status_code=404,
                detail=f"Account '{account_name}' not found"
            )
        
        # 2. Validate inputs
        if count < 1:
            raise HTTPException(
                status_code=400,
                detail="Count must be at least 1"
            )
        
        # 3. Determine price and validate based on order type
        if type == "market":
            # Market orders don't require price specification
            # Use placeholder price (50 cents) for the order record
            # Actual fill price will be determined at execution time
            price_cents = 50
        else:  # type == "limit"
            # Limit orders require price specification
            if action == "buy":
                # Determine which price to use based on side
                if side == "yes":
                    if yes_price is None:
                        raise HTTPException(
                            status_code=400,
                            detail="yes_price is required for limit orders on yes side"
                        )
                    price_cents = yes_price
                else:  # side == "no"
                    if no_price is None:
                        raise HTTPException(
                            status_code=400,
                            detail="no_price is required for limit orders on no side"
                        )
                    price_cents = no_price
                
                # Validate price range
                if price_cents < 1 or price_cents > 99:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Price must be between 1 and 99 cents, got {price_cents}"
                    )
            else:  # action == "sell"
                # For sell orders, we need to determine the price for the order record
                if side == "yes":
                    if yes_price is None:
                        raise HTTPException(
                            status_code=400,
                            detail="yes_price is required for limit orders on yes side"
                        )
                    price_cents = yes_price
                else:  # side == "no"
                    if no_price is None:
                        raise HTTPException(
                            status_code=400,
                            detail="no_price is required for limit orders on no side"
                        )
                    price_cents = no_price
                
                # Validate price range
                if price_cents < 1 or price_cents > 99:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Price must be between 1 and 99 cents, got {price_cents}"
                    )
        
        # 4. Check balance for buy orders (for limit orders, use limit price; for market orders, skip balance check)
        if action == "buy" and type == "limit":
            # Calculate cost in dollars: (price_cents / 100) * count
            max_cost = Decimal(price_cents) / Decimal(100) * Decimal(count)
            
            # Check if account has sufficient balance
            if account.balance < max_cost:
                raise HTTPException(
                    status_code=400,
                    detail=f"Insufficient balance. Required: ${max_cost}, Available: ${account.balance}"
                )
        
        # 5. Set default expiration if not provided (5 minutes from now)
        if expiration_ts is None:
            expiration_ts = int(DateTime.now().timestamp()) + 300  # 5 minutes
        
        # 6. Create the order record
        order = KalshiOrder(
            account_id=account.account_id,
            ticker=ticker,
            side=KalshiOrderSide(side),
            action=KalshiOrderAction(action),
            count=count,
            type=KalshiOrderType(type),
            status=KalshiOrderStatus.OPEN,
            price=price_cents,
            expiration_ts=expiration_ts,
        )
        
        db.add(order)
        await db.commit()
        await db.refresh(order)
        
        # 7. Return success response
        return {
            "order_id": str(order.order_id),
            "account_id": str(order.account_id),
            "ticker": order.ticker,
            "side": order.side.value,
            "action": order.action.value,
            "count": order.count,
            "type": order.type.value,
            "status": order.status.value,
            "price": order.price,
            "price_dollars": f"{order.price / 100:.2f}",
            "expiration_ts": order.expiration_ts,
            "created_at": order.created_at.isoformat(),
        }
        
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create order: {str(e)}"
        )


# Request/Response Models
class CreateKalshiAccountRequest(BaseModel):
    """Request model for creating a Kalshi account"""
    account_name: str
    key_id: str
    secret_name: str
    is_demo: bool = False


class CreateKalshiAccountResponse(BaseModel):
    """Response model for creating a Kalshi account"""
    account_id: str
    account_name: str
    key_id: str
    secret_name: str
    is_demo: bool


class GetKalshiBalanceResponse(BaseModel):
    """Response model for Kalshi balance endpoint"""
    balance: int  # Member's available balance in cents
    portfolio_value: int  # Member's portfolio value in cents
    updated_ts: int  # Unix timestamp of the last update


class KalshiPositionItem(BaseModel):
    """Model for a single Kalshi position"""
    ticker: str
    side: str  # 'yes' or 'no'
    position: int  # Absolute position size


class GetKalshiAccountPositionsResponse(BaseModel):
    """Response model for Kalshi account positions endpoint"""
    positions: list[KalshiPositionItem]


class KalshiMarketResponse(BaseModel):
    """Response model for Kalshi market data from API"""
    ticker: str
    event_ticker: str
    title: str
    subtitle: str
    status: str
    volume: int
    volume_24h: int
    liquidity: int
    yes_bid: int
    yes_ask: int
    no_bid: int
    no_ask: int
    yes_bid_dollars: str
    yes_ask_dollars: str
    no_bid_dollars: str
    no_ask_dollars: str
    last_price: int
    open_interest: int
    close_time: str
    
    # Additional fields from API (optional)
    market_type: Optional[str] = None
    yes_sub_title: Optional[str] = None
    no_sub_title: Optional[str] = None
    created_time: Optional[str] = None
    open_time: Optional[str] = None
    expiration_time: Optional[str] = None
    latest_expiration_time: Optional[str] = None
    settlement_timer_seconds: Optional[int] = None
    response_price_units: Optional[str] = None
    last_price_dollars: Optional[str] = None
    result: Optional[str] = None
    can_close_early: Optional[bool] = None
    notional_value: Optional[int] = None
    notional_value_dollars: Optional[str] = None
    previous_yes_bid: Optional[int] = None
    previous_yes_bid_dollars: Optional[str] = None
    previous_yes_ask: Optional[int] = None
    previous_yes_ask_dollars: Optional[str] = None
    previous_price: Optional[int] = None
    previous_price_dollars: Optional[str] = None
    liquidity_dollars: Optional[str] = None
    expiration_value: Optional[str] = None
    category: Optional[str] = None
    risk_limit_cents: Optional[int] = None
    tick_size: Optional[int] = None
    rules_primary: Optional[str] = None
    rules_secondary: Optional[str] = None
    
    class Config:
        from_attributes = True


class GetKalshiMarketsResponse(BaseModel):
    """Response model for get markets endpoint"""
    markets: list[KalshiMarketResponse]
    total_count: int


class UpdateKalshiAccountValueResponse(BaseModel):
    """Response model for updating Kalshi account value"""
    account_id: uuid.UUID
    account_name: str
    total_value: Decimal


class KalshiAccountValueRecord(BaseModel):
    """Individual account value record"""
    timestamp: DateTime
    total_value: Decimal


class GetKalshiAccountValueHistoryResponse(BaseModel):
    """Response model for Kalshi account value history"""
    account_id: uuid.UUID
    account_name: str
    start_time: DateTime
    end_time: DateTime
    values: list[KalshiAccountValueRecord]


class ProcessKalshiOrdersResponse(BaseModel):
    """Response model for processing Kalshi orders"""
    filled_orders: list[str]  # List of order IDs that were filled
    cancelled_orders: list[str]  # List of order IDs that were cancelled
    total_processed: int  # Total number of orders processed


class SellPositionAtMarketRequest(BaseModel):
    """Request model for selling a position at market price"""
    account_name: str
    ticker: str


class SellPositionAtMarketResponse(BaseModel):
    """Response model for selling a position at market price"""
    success: bool
    message: str
    order_id: Optional[str] = None
    side: Optional[str] = None  # "yes" or "no"
    count: Optional[int] = None  # Number of contracts sold


async def get_kalshi_markets(
    db: AsyncSession,
    exclude_tickers: Optional[list[str]] = None
) -> dict:
    """
    Get all markets with latest data from Kalshi API, with optional filtering to exclude specified tickers.
    
    This function:
    1. Queries the database to get filtered market tickers (applying exclude_tickers filter)
    2. Uses those tickers to fetch the most up-to-date market data from the Kalshi API (public endpoint, no auth required)
    3. Returns fresh market data to avoid database latency issues
    
    Args:
        db: Database session
        exclude_tickers: Optional list of ticker symbols to exclude from results
        
    Returns:
        Dictionary containing:
            - markets: List of market objects with latest data from Kalshi API
            - total_count: Total number of markets returned
            
    Example:
        markets_data = await get_kalshi_markets(db, exclude_tickers=["TICKER1", "TICKER2"])
    """
    # Step 1: Query database to get filtered markets
    query = select(KalshiMarket)
    
    # Add filter to exclude specific tickers if provided
    if exclude_tickers:
        query = query.where(~KalshiMarket.ticker.in_(exclude_tickers))
    
    # Execute query to get markets and extract tickers
    result = await db.execute(query)
    markets = result.scalars().all()
    tickers = [market.ticker for market in markets]
    
    # If no tickers found, return empty result
    if not tickers:
        return {
            'markets': [],
            'total_count': 0
        }
    
    # Step 2: Use production API
    base_url = "https://api.elections.kalshi.com"
    
    # Step 3: Fetch fresh data from Kalshi API (public endpoint, no authentication required)
    path = '/trade-api/v2/markets'
    
    all_markets = []
    
    # API might have limits on tickers per request, so batch them (100 at a time)
    batch_size = 100
    async with httpx.AsyncClient() as client:
        for i in range(0, len(tickers), batch_size):
            batch_tickers = tickers[i:i + batch_size]
            
            # Build request parameters with comma-separated tickers
            params = {
                'tickers': ','.join(batch_tickers)
            }
            
            # No authentication headers needed for public markets endpoint
            response = await client.get(
                f"{base_url}{path}",
                params=params
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                # Log the error response body for debugging
                error_detail = response.text
                print(f"Kalshi API Error (get markets): Status {response.status_code}")
                print(f"Error detail: {error_detail}")
                print(f"Request URL: {base_url}{path}")
                print(f"Request params: {params}")
                print(f"Batch {i//batch_size + 1}, tickers: {batch_tickers[:5]}..." if len(batch_tickers) > 5 else f"Batch {i//batch_size + 1}, tickers: {batch_tickers}")
                raise
            data = response.json()
            
            # Accumulate markets from this batch
            all_markets.extend(data.get('markets', []))
    
    return {
        'markets': all_markets,
        'total_count': len(all_markets)
    }


async def create_kalshi_account_handler(
    request: CreateKalshiAccountRequest, db: AsyncSession
) -> CreateKalshiAccountResponse:
    """
    Create a new Kalshi account
    
    Args:
        request: CreateKalshiAccountRequest with account details
        db: Database session
        
    Returns:
        CreateKalshiAccountResponse with created account details
        
    Raises:
        ValueError: If account name already exists
    """
    # Check if account name already exists
    result = await db.execute(
        select(KalshiAccount).where(KalshiAccount.account_name == request.account_name)
    )
    existing_account = result.scalar_one_or_none()
    if existing_account:
        raise ValueError(f"Kalshi account with name '{request.account_name}' already exists")
    
    # Create new account
    new_account = KalshiAccount(
        account_name=request.account_name,
        key_id=request.key_id,
        secret_name=request.secret_name,
        is_demo=request.is_demo,
    )
    
    db.add(new_account)
    await db.commit()
    await db.refresh(new_account)
    
    return CreateKalshiAccountResponse(
        account_id=str(new_account.account_id),
        account_name=new_account.account_name,
        key_id=new_account.key_id,
        secret_name=new_account.secret_name,
        is_demo=new_account.is_demo,
    )


async def update_kalshi_account_value_handler(
    account_name: str, db: AsyncSession
) -> UpdateKalshiAccountValueResponse:
    """
    Calculate and store the Kalshi account total value (balance + position values).
    
    - Gets the account balance from the Account table
    - Gets all Kalshi positions for the account
    - Fetches market prices and calculates position values using midpoint pricing
    - Calculates total value = balance + sum(position values)
    - Stores it in the account_values table
    
    Args:
        account_name: Name of the account
        db: Database session
        
    Returns:
        UpdateKalshiAccountValueResponse with stored value details
        
    Raises:
        HTTPException: If account not found or API error
    """
    # Get account from database
    stmt = select(Account).where(Account.account_name == account_name)
    result = await db.execute(stmt)
    account = result.scalar_one_or_none()
    
    if not account:
        raise HTTPException(
            status_code=404,
            detail=f"Account '{account_name}' not found"
        )
    
    # Get account balance
    account_balance = account.balance
    
    # Get all Kalshi positions for this account
    stmt = select(KalshiPosition).where(
        KalshiPosition.account_id == account.account_id,
        KalshiPosition.position != 0  # Only get non-zero positions
    )
    result = await db.execute(stmt)
    positions = result.scalars().all()
    
    # Calculate position values
    position_values_sum = Decimal('0.00')
    
    if positions:
        # Get unique tickers from positions
        unique_tickers = list(set(pos.ticker for pos in positions))
        
        # Fetch market data for all tickers
        market_data_map = await fetch_market_data_for_tickers(unique_tickers)
        
        # Calculate value for each position using midpoint pricing
        for position in positions:
            market_data = market_data_map.get(position.ticker)
            
            if not market_data:
                # Skip positions without market data
                continue
            
            # Determine side and calculate midpoint price
            if position.position > 0:
                # Yes position - use yes midpoint
                yes_bid = market_data.get('yes_bid', 0)
                yes_ask = market_data.get('yes_ask', 0)
                midpoint_cents = (yes_bid + yes_ask) / 2
            else:
                # No position - use no midpoint
                no_bid = market_data.get('no_bid', 0)
                no_ask = market_data.get('no_ask', 0)
                midpoint_cents = (no_bid + no_ask) / 2
            
            # Convert midpoint from cents to dollars
            midpoint_dollars = Decimal(str(midpoint_cents)) / Decimal('100')
            
            # Calculate position value = abs(position) * midpoint_price
            position_value = Decimal(str(abs(position.position))) * midpoint_dollars
            position_values_sum += position_value
    
    # Calculate total value = balance + sum of position values
    total_value = account_balance + position_values_sum
    
    # Create new AccountValue record
    account_value = AccountValue(
        account_id=account.account_id,
        account_name=account.account_name,
        total_value=total_value,
    )
    
    db.add(account_value)
    await db.commit()
    await db.refresh(account_value)
    
    return UpdateKalshiAccountValueResponse(
        account_id=account.account_id,
        account_name=account.account_name,
        total_value=total_value,
    )


async def get_kalshi_account_value_history_handler(
    account_name: str,
    start_time: DateTime,
    end_time: DateTime,
    db: AsyncSession,
) -> GetKalshiAccountValueHistoryResponse:
    """
    Get Kalshi account value history between start_time and end_time.
    
    Returns all recorded account values within the specified time range,
    ordered by timestamp ascending.
    
    Args:
        account_name: Name of the account
        start_time: Start of time range
        end_time: End of time range
        db: Database session
        
    Returns:
        GetKalshiAccountValueHistoryResponse with account value history
        
    Raises:
        HTTPException: If account not found
    """
    # Get account from database
    stmt = select(Account).where(Account.account_name == account_name)
    result = await db.execute(stmt)
    account = result.scalar_one_or_none()
    
    if not account:
        raise HTTPException(
            status_code=404,
            detail=f"Account '{account_name}' not found"
        )
    
    # Query account values within the time range
    stmt = (
        select(AccountValue)
        .where(
            AccountValue.account_id == account.account_id,
            AccountValue.timestamp >= start_time,
            AccountValue.timestamp <= end_time,
        )
        .order_by(AccountValue.timestamp)
    )
    result = await db.execute(stmt)
    account_values = result.scalars().all()
    
    # Convert to response format
    values = [
        KalshiAccountValueRecord(
            timestamp=av.timestamp,
            total_value=av.total_value,
        )
        for av in account_values
    ]
    
    return GetKalshiAccountValueHistoryResponse(
        account_id=account.account_id,
        account_name=account.account_name,
        start_time=start_time,
        end_time=end_time,
        values=values,
    )


async def sell_position_at_market_handler(
    request: SellPositionAtMarketRequest,
    db: AsyncSession
) -> SellPositionAtMarketResponse:
    """
    Sell a position at market price (admin endpoint).
    
    This endpoint is for administrative use to close positions manually.
    It will place a market sell order for the entire position.
    
    Args:
        request: Request containing account_name and ticker
        db: Database session
        
    Returns:
        SellPositionAtMarketResponse with order details
        
    Raises:
        HTTPException: If account or position not found
    """
    try:
        # 1. Get the account by name
        stmt = select(Account).where(Account.account_name == request.account_name)
        result = await db.execute(stmt)
        account = result.scalar_one_or_none()
        
        if not account:
            raise HTTPException(
                status_code=404,
                detail=f"Account '{request.account_name}' not found"
            )
        
        # 2. Check if there's a position for this ticker
        position_stmt = select(KalshiPosition).where(
            KalshiPosition.account_id == account.account_id,
            KalshiPosition.ticker == request.ticker
        )
        position_result = await db.execute(position_stmt)
        position = position_result.scalar_one_or_none()
        
        # 3. If no position or position is zero, return message
        if not position or position.position == 0:
            return SellPositionAtMarketResponse(
                success=True,
                message=f"No position found for ticker '{request.ticker}' in account '{request.account_name}'",
            )
        
        # 4. Determine side and count based on position
        # Positive position = yes side, negative position = no side
        if position.position > 0:
            side = "yes"
            count = position.position
        else:
            side = "no"
            count = abs(position.position)
        
        # 5. Place market sell order to close the position
        order_response = await create_kalshi_order(
            db=db,
            account_name=request.account_name,
            ticker=request.ticker,
            side=side,
            action="sell",
            count=count,
            type="market",
        )
        order_id = order_response.get('order_id')
        
        return SellPositionAtMarketResponse(
            success=True,
            message=f"Market sell order placed for {count} {side.upper()} contracts on '{request.ticker}'",
            order_id=order_id,
            side=side,
            count=count,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to sell position at market: {str(e)}"
        )

