import os
import httpx
from typing import Optional
from dotenv import load_dotenv
from google.adk.tools import ToolContext

# Load environment variables from .env file
load_dotenv()

# Risk management constants (hardcoded for safety)
DEFAULT_ENTRY_MIN_IMPLIED_EDGE = 0.05  # 5% minimum edge required
DEFAULT_ENTRY_MAX_CAPITAL_RISK = 200.0  # Maximum $200 risk per strategy
DEFAULT_ENTRY_MAX_POSITION_SHARES = 1000  # Maximum 1000 shares per position


async def get_kalshi_balance(tool_context: ToolContext) -> dict:
    """Get the current balance for a Kalshi account.
    
    This tool retrieves the current balance information from the Kalshi API including:
    - Available balance (amount available for trading)
    - Portfolio value (current value of all positions held)
    - Last update timestamp
    
    The account name is read from the session state.
    
    Returns:
        dict: A dictionary containing:
            - balance (float): Member's available balance in dollars
            - portfolio_value (float): Member's portfolio value in dollars
            - updated_ts (int): Unix timestamp of the last update
    
    Raises:
        ValueError: If POLY_PAPER_URL not set in environment or account_name not in session state
        httpx.HTTPStatusError: If the API request fails
    """
    poly_paper_url = os.getenv("POLY_PAPER_URL")
    
    if not poly_paper_url:
        raise ValueError("POLY_PAPER_URL not set in environment")
    
    # Get account_name from session state
    kalshi_account_name = tool_context.state.get("account_name")
    if not kalshi_account_name:
        raise ValueError("account_name not set in session state")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{poly_paper_url.rstrip('/')}/accounts/balance",
            params={"account_name": kalshi_account_name},
        )
        response.raise_for_status()
        data = response.json()
    
    # Convert Decimal to float
    data["balance"] = float(data["balance"])
    
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


async def get_kalshi_positions(tool_context: ToolContext) -> dict:
    """Get all positions for a Kalshi account.
    
    This tool retrieves all positions from the database for a Kalshi account.
    Only positions with non-zero values are returned.
    
    The account name is read from the session state.
    
    Returns:
        dict: A dictionary containing:
            - positions (list[dict]): List of positions with:
                - ticker (str): Market ticker
                - side (str): Position side ('yes' or 'no')
                - position (int): Absolute position size
    
    Raises:
        ValueError: If POLY_PAPER_URL not set in environment or account_name not in session state
        httpx.HTTPStatusError: If the API request fails
    """
    poly_paper_url = os.getenv("POLY_PAPER_URL")
    
    if not poly_paper_url:
        raise ValueError("POLY_PAPER_URL not set in environment")
    
    # Get account_name from session state
    kalshi_account_name = tool_context.state.get("account_name")
    if not kalshi_account_name:
        raise ValueError("account_name not set in session state")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{poly_paper_url.rstrip('/')}/kalshi/positions",
            params={"account_name": kalshi_account_name},
        )
        response.raise_for_status()
        data = response.json()
    
    return data


async def create_kalshi_strategy(
    ticker: str,
    thesis: str,
    thesis_probability: float,
    entry_max_price: float,
    exit_take_profit_price: float,
    exit_stop_loss_price: float,
    tool_context: ToolContext,
    side: str = "yes",
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
    
    The account name is read from the session state.
    
    Risk management parameters are hardcoded for safety:
    - Minimum implied edge: 5% (DEFAULT_ENTRY_MIN_IMPLIED_EDGE)
    - Maximum capital risk: $200 per strategy (DEFAULT_ENTRY_MAX_CAPITAL_RISK)
    - Maximum position shares: 1000 shares (DEFAULT_ENTRY_MAX_POSITION_SHARES)
    
    Args:
        ticker (str): Market ticker symbol (e.g., "KXBTC-24DEC31-T100000")
        thesis (str): Your detailed reasoning for why you believe in this trade.
            Explain what research you did, what you found, and why you think
            the market is mispriced.
        thesis_probability (float): Your estimated probability of the outcome (0.0 to 1.0).
            For example, 0.68 means you estimate 68% chance of the outcome.
        entry_max_price (float): Maximum price you're willing to pay to enter (0.0 to 1.0).
            The strategy will only buy if ask price is at or below this.
        exit_take_profit_price (float): Price at which to sell for profit (0.0 to 1.0).
            When bid price reaches this, all shares will be sold.
        exit_stop_loss_price (float): Price at which to cut losses (0.0 to 1.0).
            When bid price falls to this, all shares will be sold to limit losses.
        tool_context (ToolContext): Tool context for accessing session state
        side (str): Which side to bet on - "yes" or "no". Defaults to "yes".
            - "yes": Betting that the event will happen
            - "no": Betting that the event will NOT happen
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
        ValueError: If POLY_PAPER_URL not set in environment or account_name not in session state
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
            tool_context=tool_context,
            notes="Monitor ETF flows and Fed policy announcements"
        )
    """
    poly_paper_url = os.getenv("POLY_PAPER_URL")
    
    if not poly_paper_url:
        raise ValueError("POLY_PAPER_URL not set in environment")
    
    # Get account_name from session state
    kalshi_account_name = tool_context.state.get("account_name")
    if not kalshi_account_name:
        raise ValueError("account_name not set in session state")
    
    # Build request payload
    payload = {
        "account_name": kalshi_account_name,
        "ticker": ticker,
        "side": side,
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


async def get_active_kalshi_strategies(tool_context: ToolContext) -> dict:
    """Get all active strategies for the Kalshi account with current market data.
    
    This tool retrieves all active trading strategies for your Kalshi account.
    A strategy is considered active if:
    - valid_until_utc is later than the current time, OR
    - valid_until_utc is not set (null)
    
    Active strategies are being monitored and will automatically execute trades
    based on their entry/exit conditions.
    
    The account name is read from the session state.
    
    IMPORTANT: This now includes real-time market data for each strategy, allowing you to
    see current prices and calculate the edge.
    
    Args:
        tool_context (ToolContext): Tool context for accessing session state
    
    Returns:
        dict: A dictionary containing:
            - account_name (str): The account name
            - strategies (list[dict]): List of active strategy objects with:
                Strategy fields:
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
                
                Current market data fields:
                - current_yes_bid (Optional[float]): Current YES bid price (0.0-1.0)
                - current_yes_ask (Optional[float]): Current YES ask price (0.0-1.0)
                - current_no_bid (Optional[float]): Current NO bid price (0.0-1.0)
                - current_no_ask (Optional[float]): Current NO ask price (0.0-1.0)
                - market_status (Optional[str]): Market status (open, closed, settled, etc.)
                - market_close_time (Optional[str]): Market close time (ISO format)
                - market_expected_expiration_time (Optional[str]): Expected settlement (ISO format)
                
                Calculated fields:
                - current_edge (Optional[float]): thesis_probability - current_yes_ask
    
    Raises:
        ValueError: If POLY_PAPER_URL not set in environment or account_name not in session state
        httpx.HTTPStatusError: If the API request fails
    
    Example:
        # Get all active strategies with market data
        result = await get_active_kalshi_strategies(tool_context)
        print(f"Found {len(result['strategies'])} active strategies")
        for strategy in result['strategies']:
            ticker = strategy['ticker']
            current_ask = strategy.get('current_yes_ask', 'N/A')
            current_edge = strategy.get('current_edge', 'N/A')
            print(f"  - {ticker}: Ask ${current_ask}, Edge: {current_edge}")
    """
    poly_paper_url = os.getenv("POLY_PAPER_URL")
    
    if not poly_paper_url:
        raise ValueError("POLY_PAPER_URL not set in environment")
    
    # Get account_name from session state
    kalshi_account_name = tool_context.state.get("account_name")
    if not kalshi_account_name:
        raise ValueError("account_name not set in session state")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{poly_paper_url.rstrip('/')}/strategies/active",
            params={"account_name": kalshi_account_name},
        )
        response.raise_for_status()
        data = response.json()
    
    # Convert Decimal fields to float for easier consumption in all strategies
    for strategy in data.get("strategies", []):
        # Strategy fields
        strategy["thesis_probability"] = float(strategy["thesis_probability"])
        strategy["entry_max_price"] = float(strategy["entry_max_price"])
        strategy["entry_min_implied_edge"] = float(strategy["entry_min_implied_edge"])
        strategy["entry_max_capital_risk"] = float(strategy["entry_max_capital_risk"])
        strategy["exit_take_profit_price"] = float(strategy["exit_take_profit_price"])
        strategy["exit_stop_loss_price"] = float(strategy["exit_stop_loss_price"])
        
        # Market data fields (convert if present)
        if strategy.get("current_yes_bid") is not None:
            strategy["current_yes_bid"] = float(strategy["current_yes_bid"])
        if strategy.get("current_yes_ask") is not None:
            strategy["current_yes_ask"] = float(strategy["current_yes_ask"])
        if strategy.get("current_no_bid") is not None:
            strategy["current_no_bid"] = float(strategy["current_no_bid"])
        if strategy.get("current_no_ask") is not None:
            strategy["current_no_ask"] = float(strategy["current_no_ask"])
        if strategy.get("current_edge") is not None:
            strategy["current_edge"] = float(strategy["current_edge"])
    
    return data


async def update_kalshi_strategy(
    strategy_id: str,
    thesis: Optional[str] = None,
    thesis_probability: Optional[float] = None,
    entry_max_price: Optional[float] = None,
    exit_take_profit_price: Optional[float] = None,
    exit_stop_loss_price: Optional[float] = None,
    exit_time_stop_utc: Optional[str] = None,
    valid_until_utc: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    """Update an existing trading strategy using an immutable update pattern.
    
    This tool updates a strategy by:
    1. Finding the existing strategy by strategy_id
    2. Expiring it (setting valid_until_utc to now)
    3. Creating a new strategy with updated values and a new strategy_id
    
    This immutable pattern preserves the history of strategy changes.
    Only provide the fields you want to update - unchanged fields will be
    carried over from the old strategy.
    
    Args:
        strategy_id (str): The ID of the strategy to update (required)
        thesis (Optional[str]): Updated reasoning for the trade
        thesis_probability (Optional[float]): Updated probability estimate (0.0-1.0)
        entry_max_price (Optional[float]): Updated max entry price (0.0-1.0)
        exit_take_profit_price (Optional[float]): Updated take profit price (0.0-1.0)
        exit_stop_loss_price (Optional[float]): Updated stop loss price (0.0-1.0)
        exit_time_stop_utc (Optional[str]): Updated time-based exit (ISO format)
        valid_until_utc (Optional[str]): Updated strategy expiration (ISO format)
        notes (Optional[str]): Updated additional notes
    
    Returns:
        dict: A dictionary containing:
            - old_strategy_id (str): The ID of the expired strategy
            - new_strategy (dict): The new strategy object with:
                - strategy_id (str): New unique ID for the updated strategy
                - account_name (str): Account name
                - ticker (str): Market ticker
                - thesis (str): Reasoning (updated or original)
                - thesis_probability (float): Probability estimate
                - entry_max_price (float): Max entry price
                - entry_min_implied_edge (float): Min required edge
                - entry_max_capital_risk (float): Max capital to risk
                - entry_max_position_shares (int): Max shares
                - exit_take_profit_price (float): Take profit price
                - exit_stop_loss_price (float): Stop loss price
                - exit_time_stop_utc (Optional[str]): Time-based exit
                - valid_until_utc (Optional[str]): Strategy expiration
                - notes (Optional[str]): Additional notes
                - created_at (str): Creation timestamp of new strategy
                - updated_at (str): Last update timestamp
    
    Raises:
        ValueError: If POLY_PAPER_URL not set in environment
        httpx.HTTPStatusError: If the API request fails (e.g., strategy not found, already expired)
    
    Example:
        # Update the take profit and stop loss for a strategy
        result = await update_kalshi_strategy(
            strategy_id="abc123-def456-789",
            exit_take_profit_price=0.95,  # Raise take profit
            exit_stop_loss_price=0.35,    # Tighten stop loss
            notes="Adjusted based on new market conditions"
        )
        print(f"Old strategy {result['old_strategy_id']} replaced with {result['new_strategy']['strategy_id']}")
    """
    poly_paper_url = os.getenv("POLY_PAPER_URL")
    
    if not poly_paper_url:
        raise ValueError("POLY_PAPER_URL not set in environment")
    
    # Build request payload with only the fields to update
    payload = {
        "strategy_id": strategy_id,
    }
    
    # Add optional fields if provided
    if thesis is not None:
        payload["thesis"] = thesis
    if thesis_probability is not None:
        payload["thesis_probability"] = thesis_probability
    if entry_max_price is not None:
        payload["entry_max_price"] = entry_max_price
    if exit_take_profit_price is not None:
        payload["exit_take_profit_price"] = exit_take_profit_price
    if exit_stop_loss_price is not None:
        payload["exit_stop_loss_price"] = exit_stop_loss_price
    if exit_time_stop_utc is not None:
        payload["exit_time_stop_utc"] = exit_time_stop_utc
    if valid_until_utc is not None:
        payload["valid_until_utc"] = valid_until_utc
    if notes is not None:
        payload["notes"] = notes
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.put(
            f"{poly_paper_url.rstrip('/')}/strategies",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
    
    # Convert Decimal fields to float in the new strategy
    new_strategy = data.get("new_strategy", {})
    new_strategy["thesis_probability"] = float(new_strategy["thesis_probability"])
    new_strategy["entry_max_price"] = float(new_strategy["entry_max_price"])
    new_strategy["entry_min_implied_edge"] = float(new_strategy["entry_min_implied_edge"])
    new_strategy["entry_max_capital_risk"] = float(new_strategy["entry_max_capital_risk"])
    new_strategy["exit_take_profit_price"] = float(new_strategy["exit_take_profit_price"])
    new_strategy["exit_stop_loss_price"] = float(new_strategy["exit_stop_loss_price"])
    
    return data


async def remove_kalshi_strategy(strategy_id: str) -> dict:
    """Remove (expire) a trading strategy by setting its valid_until_utc to now.
    
    This tool deactivates a strategy so it will no longer execute trades.
    The strategy is not deleted from the database - it's just expired for
    record-keeping and audit purposes.

    Note: Removing a strategy will also sell all the positions related to this strategy
    at market price.
    
    Use this when:
    - You want to stop a strategy from executing any more trades
    - Market conditions have changed and the strategy is no longer valid
    - You've changed your thesis and don't want the strategy active anymore
    - You want to close out a position manually instead of waiting for exit conditions
    
    Args:
        strategy_id (str): The ID of the strategy to remove
    
    Returns:
        dict: A dictionary containing:
            - success (bool): True if the strategy was successfully removed
            - strategy_id (str): The ID of the removed strategy
            - message (str): Confirmation message
    
    Raises:
        ValueError: If POLY_PAPER_URL not set in environment
        httpx.HTTPStatusError: If the API request fails (e.g., strategy not found, already expired)
    
    Example:
        # Remove a strategy that's no longer needed
        result = await remove_kalshi_strategy("abc123-def456-789")
        if result["success"]:
            print(result["message"])
        
        # Example output:
        # "Strategy for KXBTC-24DEC31-T100000 has been successfully removed (expired)"
    """
    poly_paper_url = os.getenv("POLY_PAPER_URL")
    
    if not poly_paper_url:
        raise ValueError("POLY_PAPER_URL not set in environment")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.delete(
            f"{poly_paper_url.rstrip('/')}/strategies",
            params={"strategy_id": strategy_id},
        )
        response.raise_for_status()
        data = response.json()
    
    return data

