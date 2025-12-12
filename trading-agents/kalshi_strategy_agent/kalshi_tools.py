import os
import httpx
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Risk management constants (hardcoded for safety)
DEFAULT_ENTRY_MIN_IMPLIED_EDGE = 0.05  # 5% minimum edge required
DEFAULT_ENTRY_MAX_CAPITAL_RISK = 200.0  # Maximum $200 risk per strategy
DEFAULT_ENTRY_MAX_POSITION_SHARES = 1000  # Maximum 1000 shares per position


async def get_kalshi_balance() -> dict:
    """Get the current balance for a Kalshi account.
    
    This tool retrieves the current balance information from the Kalshi API including:
    - Available balance (amount available for trading)
    - Portfolio value (current value of all positions held)
    - Last update timestamp
    
    Returns:
        dict: A dictionary containing:
            - balance (float): Member's available balance in dollars
            - portfolio_value (float): Member's portfolio value in dollars
            - updated_ts (int): Unix timestamp of the last update
    
    Raises:
        ValueError: If POLY_PAPER_URL or KALSHI_ACCOUNT_NAME not set in environment
        httpx.HTTPStatusError: If the API request fails
    """
    poly_paper_url = os.getenv("POLY_PAPER_URL")
    kalshi_account_name = os.getenv("KALSHI_ACCOUNT_NAME")
    
    if not poly_paper_url:
        raise ValueError("POLY_PAPER_URL not set in environment")
    if not kalshi_account_name:
        raise ValueError("KALSHI_ACCOUNT_NAME not set in environment")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{poly_paper_url.rstrip('/')}/kalshi/balance",
            params={"account_name": kalshi_account_name},
        )
        response.raise_for_status()
        data = response.json()
    
    # Convert cents to dollars
    data["balance"] = data["balance"] / 100.0
    data["portfolio_value"] = data["portfolio_value"] / 100.0
    
    return data


async def list_new_markets(exclude_tickers: Optional[list[str]] = None) -> dict:
    """List Kalshi markets with optional filtering.
    
    This tool retrieves all available Kalshi markets with the latest data from the Kalshi API.
    You can optionally exclude specific tickers from the results.
    
    Args:
        exclude_tickers (Optional[list[str]]): Optional list of ticker symbols to exclude from results.
            For example, ["TICKER1", "TICKER2"] to exclude those specific markets.
    
    Returns:
        dict: A dictionary containing:
            - markets (list[dict]): List of market objects with:
                - ticker (str): Market ticker symbol
                - title (str): Market title/description
                - status (str): Market status (open, closed, settled, etc.)
                - close_time (str): Market close time (ISO format)
                - expected_expiration_time (str): Expected settlement time (ISO format)
                - subtitle (str): Market subtitle
                - yes_bid (float): Current yes bid price in dollars
                - yes_ask (float): Current yes ask price in dollars
                - no_bid (float): Current no bid price in dollars
                - no_ask (float): Current no ask price in dollars
            - total_count (int): Total number of markets returned (after filtering)
    
    Raises:
        ValueError: If POLY_PAPER_URL not set in environment
        httpx.HTTPStatusError: If the API request fails
    """
    poly_paper_url = os.getenv("POLY_PAPER_URL")
    
    if not poly_paper_url:
        raise ValueError("POLY_PAPER_URL not set in environment")
    
    params = {}
    if exclude_tickers:
        params["exclude_tickers"] = exclude_tickers
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{poly_paper_url.rstrip('/')}/kalshi/markets",
            params=params,
        )
        response.raise_for_status()
        data = response.json()
    
    # Filter and convert market data to only include relevant fields
    filtered_markets = []
    for market in data.get("markets", []):
        filtered_market = {
            "ticker": market.get("ticker"),
            "title": market.get("title"),
            "status": market.get("status"),
            "close_time": market.get("close_time"),
            "expected_expiration_time": market.get("expected_expiration_time"),
            "subtitle": market.get("subtitle"),
            "yes_bid": float(market["yes_bid_dollars"]) if "yes_bid_dollars" in market else None,
            "yes_ask": float(market["yes_ask_dollars"]) if "yes_ask_dollars" in market else None,
            "no_bid": float(market["no_bid_dollars"]) if "no_bid_dollars" in market else None,
            "no_ask": float(market["no_ask_dollars"]) if "no_ask_dollars" in market else None,
        }
        filtered_markets.append(filtered_market)
    
    return {
        "markets": filtered_markets,
        "total_count": data.get("total_count", len(filtered_markets))
    }


async def get_kalshi_positions() -> dict:
    """Get all positions for a Kalshi account.
    
    This tool retrieves all positions (market and event level) for a Kalshi account.
    Only positions with non-zero values are returned.
    
    Returns:
        dict: A dictionary containing:
            - market_positions (list[dict]): List of market-level positions with:
                - ticker (str): Market ticker
                - position (int): Position size
                - total_traded (int): Total amount traded
                - market_exposure (float): Current market exposure in dollars
                - realized_pnl (float): Realized profit/loss in dollars
                - fees_paid (float): Total fees paid in dollars
            - event_positions (list[dict]): List of event-level positions with:
                - event_ticker (str): Event ticker
                - total_cost (float): Total cost in dollars
                - event_exposure (float): Current event exposure in dollars
                - realized_pnl (float): Realized profit/loss in dollars
                - fees_paid (float): Total fees paid in dollars
    
    Raises:
        ValueError: If POLY_PAPER_URL or KALSHI_ACCOUNT_NAME not set in environment
        httpx.HTTPStatusError: If the API request fails
    """
    poly_paper_url = os.getenv("POLY_PAPER_URL")
    kalshi_account_name = os.getenv("KALSHI_ACCOUNT_NAME")
    
    if not poly_paper_url:
        raise ValueError("POLY_PAPER_URL not set in environment")
    if not kalshi_account_name:
        raise ValueError("KALSHI_ACCOUNT_NAME not set in environment")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{poly_paper_url.rstrip('/')}/kalshi/positions",
            params={"account_name": kalshi_account_name},
        )
        response.raise_for_status()
        data = response.json()
    
    # Convert cents to dollars for market positions
    for position in data.get("market_positions", []):
        position["market_exposure"] = position["market_exposure"] / 100.0
        position["realized_pnl"] = position["realized_pnl"] / 100.0
        position["fees_paid"] = position["fees_paid"] / 100.0
    
    # Convert cents to dollars for event positions
    for position in data.get("event_positions", []):
        position["total_cost"] = position["total_cost"] / 100.0
        position["event_exposure"] = position["event_exposure"] / 100.0
        position["realized_pnl"] = position["realized_pnl"] / 100.0
        position["fees_paid"] = position["fees_paid"] / 100.0
    
    return data


async def create_kalshi_strategy(
    ticker: str,
    thesis: str,
    thesis_probability: float,
    entry_max_price: float,
    exit_take_profit_price: float,
    exit_stop_loss_price: float,
    exit_time_stop_utc: Optional[str] = None,
    valid_until_utc: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    """Create a new trading strategy for a Kalshi market.
    
    This tool creates a trading strategy that defines:
    - Entry conditions: when and how to enter a position
    - Exit conditions: when to take profit, stop loss, or time-based exit
    - Thesis: your reasoning and probability estimate for the market outcome
    
    The strategy will be monitored and executed automatically by the system.
    Only one active strategy per market ticker is allowed at a time.
    
    Risk management parameters are hardcoded for safety:
    - Minimum implied edge: 5% (DEFAULT_ENTRY_MIN_IMPLIED_EDGE)
    - Maximum capital risk: $200 per strategy (DEFAULT_ENTRY_MAX_CAPITAL_RISK)
    - Maximum position shares: 1000 shares (DEFAULT_ENTRY_MAX_POSITION_SHARES)
    
    Args:
        ticker (str): Market ticker symbol (e.g., "KXBTC-24DEC31-T100000")
        thesis (str): Your detailed reasoning for why you believe in this trade.
            Explain what research you did, what you found, and why you think
            the market is mispriced.
        thesis_probability (float): Your estimated probability of YES outcome (0.0 to 1.0).
            For example, 0.68 means you estimate 68% chance of YES.
        entry_max_price (float): Maximum price you're willing to pay to enter (0.0 to 1.0).
            The strategy will only buy if ask price is at or below this.
        exit_take_profit_price (float): Price at which to sell for profit (0.0 to 1.0).
            When bid price reaches this, all shares will be sold.
        exit_stop_loss_price (float): Price at which to cut losses (0.0 to 1.0).
            When bid price falls to this, all shares will be sold to limit losses.
        exit_time_stop_utc (Optional[str]): Optional time-based exit in ISO format.
            For example: "2024-12-31T23:59:59Z". If set, position will be closed at this time.
        valid_until_utc (Optional[str]): Optional strategy expiration in ISO format.
            After this time, the strategy will no longer be active. If not set, strategy
            remains active indefinitely.
        notes (Optional[str]): Optional additional notes about this strategy.
    
    Returns:
        dict: A dictionary containing:
            - strategy_id (str): Unique ID for this strategy
            - account_name (str): Account the strategy is associated with
            - ticker (str): Market ticker
            - thesis (str): Your reasoning
            - thesis_probability (float): Your probability estimate
            - entry_max_price (float): Max entry price
            - entry_min_implied_edge (float): Min required edge
            - entry_max_capital_risk (float): Max capital to risk
            - entry_max_position_shares (int): Max shares to buy
            - exit_take_profit_price (float): Take profit price
            - exit_stop_loss_price (float): Stop loss price
            - exit_time_stop_utc (Optional[str]): Time-based exit
            - valid_until_utc (Optional[str]): Strategy expiration
            - notes (Optional[str]): Additional notes
            - created_at (str): Strategy creation timestamp
    
    Raises:
        ValueError: If POLY_PAPER_URL or KALSHI_ACCOUNT_NAME not set in environment
        httpx.HTTPStatusError: If the API request fails (e.g., strategy already exists for this ticker)
    
    Example:
        # Create a strategy for a Bitcoin market
        strategy = await create_kalshi_strategy(
            ticker="KXBTC-24DEC31-T100000",
            thesis="Based on recent institutional adoption and ETF inflows, I believe Bitcoin will reach $100k by year end. Technical indicators show strong momentum.",
            thesis_probability=0.70,
            entry_max_price=0.55,
            exit_take_profit_price=0.90,
            exit_stop_loss_price=0.30,
            notes="Monitor ETF flows and Fed policy announcements"
        )
    """
    poly_paper_url = os.getenv("POLY_PAPER_URL")
    kalshi_account_name = os.getenv("KALSHI_ACCOUNT_NAME")
    
    if not poly_paper_url:
        raise ValueError("POLY_PAPER_URL not set in environment")
    if not kalshi_account_name:
        raise ValueError("KALSHI_ACCOUNT_NAME not set in environment")
    
    # Build request payload
    payload = {
        "account_name": kalshi_account_name,
        "ticker": ticker,
        "thesis": thesis,
        "thesis_probability": thesis_probability,
        "entry_max_price": entry_max_price,
        "entry_min_implied_edge": DEFAULT_ENTRY_MIN_IMPLIED_EDGE,
        "entry_max_capital_risk": DEFAULT_ENTRY_MAX_CAPITAL_RISK,
        "entry_max_position_shares": DEFAULT_ENTRY_MAX_POSITION_SHARES,
        "exit_take_profit_price": exit_take_profit_price,
        "exit_stop_loss_price": exit_stop_loss_price,
    }
    
    # Add optional fields if provided
    if exit_time_stop_utc:
        payload["exit_time_stop_utc"] = exit_time_stop_utc
    if valid_until_utc:
        payload["valid_until_utc"] = valid_until_utc
    if notes:
        payload["notes"] = notes
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{poly_paper_url.rstrip('/')}/strategies",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
    
    # Convert Decimal fields to float for easier consumption
    data["thesis_probability"] = float(data["thesis_probability"])
    data["entry_max_price"] = float(data["entry_max_price"])
    data["entry_min_implied_edge"] = float(data["entry_min_implied_edge"])
    data["entry_max_capital_risk"] = float(data["entry_max_capital_risk"])
    data["exit_take_profit_price"] = float(data["exit_take_profit_price"])
    data["exit_stop_loss_price"] = float(data["exit_stop_loss_price"])
    
    return data


async def get_active_kalshi_strategies() -> dict:
    """Get all active strategies for the Kalshi account.
    
    This tool retrieves all active trading strategies for your Kalshi account.
    A strategy is considered active if:
    - valid_until_utc is later than the current time, OR
    - valid_until_utc is not set (null)
    
    Active strategies are being monitored and will automatically execute trades
    based on their entry/exit conditions.
    
    Returns:
        dict: A dictionary containing:
            - account_name (str): The account name
            - strategies (list[dict]): List of active strategy objects with:
                - strategy_id (str): Unique strategy ID
                - account_name (str): Account name
                - ticker (str): Market ticker
                - thesis (str): Your reasoning for this trade
                - thesis_probability (float): Your probability estimate (0.0-1.0)
                - entry_max_price (float): Max entry price (0.0-1.0)
                - entry_min_implied_edge (float): Min required edge (0.0-1.0)
                - entry_max_capital_risk (float): Max capital to risk in dollars
                - entry_max_position_shares (int): Max shares to buy
                - exit_take_profit_price (float): Take profit price (0.0-1.0)
                - exit_stop_loss_price (float): Stop loss price (0.0-1.0)
                - exit_time_stop_utc (Optional[str]): Time-based exit (ISO format)
                - valid_until_utc (Optional[str]): Strategy expiration (ISO format)
                - notes (Optional[str]): Additional notes
                - created_at (str): Strategy creation timestamp
                - updated_at (str): Last update timestamp
    
    Raises:
        ValueError: If POLY_PAPER_URL or KALSHI_ACCOUNT_NAME not set in environment
        httpx.HTTPStatusError: If the API request fails
    
    Example:
        # Get all active strategies
        result = await get_active_kalshi_strategies()
        print(f"Found {len(result['strategies'])} active strategies")
        for strategy in result['strategies']:
            print(f"  - {strategy['ticker']}: {strategy['thesis'][:50]}...")
    """
    poly_paper_url = os.getenv("POLY_PAPER_URL")
    kalshi_account_name = os.getenv("KALSHI_ACCOUNT_NAME")
    
    if not poly_paper_url:
        raise ValueError("POLY_PAPER_URL not set in environment")
    if not kalshi_account_name:
        raise ValueError("KALSHI_ACCOUNT_NAME not set in environment")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{poly_paper_url.rstrip('/')}/strategies/active",
            params={"account_name": kalshi_account_name},
        )
        response.raise_for_status()
        data = response.json()
    
    # Convert Decimal fields to float for easier consumption in all strategies
    for strategy in data.get("strategies", []):
        strategy["thesis_probability"] = float(strategy["thesis_probability"])
        strategy["entry_max_price"] = float(strategy["entry_max_price"])
        strategy["entry_min_implied_edge"] = float(strategy["entry_min_implied_edge"])
        strategy["entry_max_capital_risk"] = float(strategy["entry_max_capital_risk"])
        strategy["exit_take_profit_price"] = float(strategy["exit_take_profit_price"])
        strategy["exit_stop_loss_price"] = float(strategy["exit_stop_loss_price"])
    
    return data

