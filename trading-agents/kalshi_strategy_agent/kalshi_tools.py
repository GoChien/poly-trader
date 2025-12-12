import os
import httpx
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


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

