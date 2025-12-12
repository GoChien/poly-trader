import os
import httpx
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

