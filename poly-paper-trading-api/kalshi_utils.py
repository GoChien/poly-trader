import os
import base64
import datetime
import uuid
from datetime import datetime as DateTime
from decimal import Decimal
from typing import Optional
import httpx
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
from models.account import AccountValue
from models.position import KalshiPosition


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


async def get_kalshi_account_positions(db: AsyncSession, account_name: str) -> dict:
    """
    Get all portfolio positions from the database
    
    Args:
        db: Database session
        account_name: Name of the Kalshi account
        
    Returns:
        Dictionary containing:
            - positions: List of positions with ticker, side, and absolute position
    """
    # Get account credentials from database
    account = await _get_kalshi_account(db, account_name)
    
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
    Create an order on Kalshi using their API.
    
    Reference: https://docs.kalshi.com/api-reference/orders/create-order
    
    Args:
        db: Database session
        account_name: Name of the Kalshi account
        ticker: Market ticker symbol
        side: "yes" or "no" - which side to bet on
        action: "buy" or "sell"
        count: Number of contracts (must be >= 1)
        expiration_ts: Optional expiration timestamp in seconds (Unix timestamp). 
                      Defaults to 10 minutes from now for limit orders. Not used for market orders.
        yes_price: Optional yes price in cents (1-99) for limit orders
        no_price: Optional no price in cents (1-99) for limit orders
        type: Order type - "market" or "limit" (default: "market")
        
    Returns:
        Dictionary containing the created order details with fields:
            - order_id (str): Unique order ID
            - ticker (str): Market ticker
            - side (str): "yes" or "no"
            - action (str): "buy" or "sell"
            - type (str): "limit" or "market"
            - status (str): "resting", "canceled", or "executed"
            - yes_price (int): Yes price in cents
            - no_price (int): No price in cents
            - yes_price_dollars (str): Yes price in dollars
            - no_price_dollars (str): No price in dollars
            - fill_count (int): Number of contracts filled
            - remaining_count (int): Number of contracts remaining
            - initial_count (int): Initial order size
            - created_time (str): ISO timestamp
            
    Raises:
        ValueError: If account not found or invalid parameters
        httpx.HTTPStatusError: If the API request fails
    """
    # Get account credentials from database
    account = await _get_kalshi_account(db, account_name)
    
    # Set default expiration to 10 minutes from now for limit orders if not provided
    if type == "limit" and expiration_ts is None:
        expiration_ts = int(datetime.datetime.now().timestamp() + 600)
    
    # Get GCP project ID from environment
    gcp_project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
    if not gcp_project_id:
        raise ValueError("GOOGLE_CLOUD_PROJECT environment variable must be set")
    
    # Load private key
    private_key = _load_private_key(gcp_project_id, account.secret_name)
    
    # Determine base URL based on is_demo flag
    base_url = "https://demo-api.kalshi.co" if account.is_demo else "https://api.elections.kalshi.com"
    
    # Build order payload
    path = '/trade-api/v2/portfolio/orders'
    method = 'POST'
    
    payload = {
        "ticker": ticker,
        "side": side,
        "action": action,
        "count": count,
        "type": type,
    }
    
    # Add optional fields
    # Only add expiration_ts for limit orders
    if type == "limit" and expiration_ts:
        payload["expiration_ts"] = expiration_ts
    if yes_price is not None:
        payload["yes_price"] = yes_price
    if no_price is not None:
        payload["no_price"] = no_price
    
    # Get authentication headers
    headers = _get_headers(private_key, account.key_id, method, path)
    headers['Content-Type'] = 'application/json'
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{base_url}{path}",
            headers=headers,
            json=payload
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            # Log the error response body for debugging
            error_detail = response.text
            print(f"Kalshi API Error: {error_detail}")
            print(f"Request payload: {payload}")
            raise
        return response.json()


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
    Calculate and store the Kalshi account total value (balance + portfolio value).
    
    - Gets the balance and portfolio value from Kalshi API
    - Calculates total value = balance + portfolio_value
    - Stores it in the account_values table
    
    Args:
        account_name: Name of the Kalshi account
        db: Database session
        
    Returns:
        UpdateKalshiAccountValueResponse with stored value details
        
    Raises:
        HTTPException: If account not found or API error
    """
    # Get Kalshi account from database
    account = await _get_kalshi_account(db, account_name)
    
    # Get balance data from Kalshi API
    balance_data = await get_kalshi_account_balance(db, account_name)
    
    # Extract balance and portfolio_value from API response (both in cents)
    balance_cents = balance_data.get('balance', 0)
    portfolio_value_cents = balance_data.get('portfolio_value', 0)
    
    # Convert cents to dollars
    balance = Decimal(str(balance_cents)) / Decimal('100')
    portfolio_value = Decimal(str(portfolio_value_cents)) / Decimal('100')
    
    # Calculate total value = balance + portfolio_value
    total_value = balance + portfolio_value
    
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
        account_name: Name of the Kalshi account
        start_time: Start of time range
        end_time: End of time range
        db: Database session
        
    Returns:
        GetKalshiAccountValueHistoryResponse with account value history
        
    Raises:
        HTTPException: If account not found
    """
    # Get Kalshi account from database
    account = await _get_kalshi_account(db, account_name)
    
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

