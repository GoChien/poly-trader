import os
from typing import Optional

import httpx

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


# Risk management constants (hardcoded for safety)
DEFAULT_ENTRY_MIN_IMPLIED_EDGE = 0.05  # 5% minimum edge required
DEFAULT_ENTRY_MAX_CAPITAL_RISK = 1000.0  # Maximum $1000 risk per strategy
DEFAULT_ENTRY_MAX_POSITION_SHARES = 1000  # Maximum 1000 shares per position


async def get_active_strategies() -> dict:
    """Get all active strategies for the account.
    
    A strategy is considered active if valid_until_utc is later than the current time,
    or if valid_until_utc is not set (null).
    
    Returns:
        dict: A dictionary containing:
            - account_name (str): The name of the account
            - strategies (list[dict]): A list of active strategy dictionaries with:
                - strategy_id: Unique identifier for the strategy
                - account_id: The account this strategy belongs to
                - token_id: The token ID this strategy trades
                - thesis: A clear, evidence-based explanation of *why* this trade should have positive expected value. 
                  It should summarize the key reasoning behind your probability estimate. 
                - thesis_probability: Estimated probability (e.g., 0.68)
                - entry_max_price: Maximum price to enter position
                - entry_min_implied_edge: Minimum edge required (thesis_prob - price)
                - entry_max_capital_risk: Maximum capital to risk
                - entry_max_position_shares: Maximum shares to hold
                - exit_take_profit_price: Price to take profit
                - exit_stop_loss_price: Price to stop loss
                - exit_time_stop_utc: Time to exit position (optional)
                - valid_until_utc: When strategy expires (optional)
                - notes: Additional notes (optional)
                - created_at: When strategy was created
                - updated_at: When strategy was last updated
    """
    poly_paper_url = os.getenv("POLY_PAPER_URL")
    poly_paper_account_name = os.getenv("POLY_PAPER_ACCOUNT_NAME")
    
    if not poly_paper_url:
        raise ValueError("POLY_PAPER_URL not set in environment")
    if not poly_paper_account_name:
        raise ValueError("POLY_PAPER_ACCOUNT_NAME not set in environment")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{poly_paper_url.rstrip('/')}/strategies/active",
            params={"account_name": poly_paper_account_name},
        )
        response.raise_for_status()
        data = response.json()
    
    return data


async def create_strategy(
    token_id: str,
    thesis: str,
    thesis_probability: float,
    entry_max_price: float,
    exit_take_profit_price: float,
    exit_stop_loss_price: float,
    exit_time_stop_utc: Optional[str] = None,
    valid_until_utc: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    """Create a new trading strategy for the account.
    
    A strategy defines entry/exit conditions for a specific market position.
    Some risk management fields are hardcoded for safety.
    
    Args:
        token_id (str): The token ID of the market outcome to trade.
        thesis (str): A clear, evidence-based explanation of *why* this trade should have 
            positive expected value. It should summarize the key reasoning behind your 
            probability estimate.
        thesis_probability (float): Your estimated probability that this outcome occurs 
            (between 0.0 and 1.0, e.g., 0.68 for 68%).
        entry_max_price (float): Maximum price you're willing to pay to enter the position 
            (between 0.0 and 1.0).
        exit_take_profit_price (float): Price at which to take profit and exit 
            (between 0.0 and 1.0).
        exit_stop_loss_price (float): Price at which to cut losses and exit 
            (between 0.0 and 1.0).
        exit_time_stop_utc (str, optional): ISO 8601 datetime string for time-based exit 
            (e.g., "2025-12-31T23:59:59Z").
        valid_until_utc (str, optional): ISO 8601 datetime string for when strategy expires 
            (e.g., "2025-12-31T23:59:59Z").
        notes (str, optional): Additional notes or context for this strategy.
    
    Returns:
        dict: The created strategy if successful, or raises an error with details on failure.
    """
    poly_paper_url = os.getenv("POLY_PAPER_URL")
    poly_paper_account_id = os.getenv("POLY_PAPER_ACCOUNT_ID")
    
    if not poly_paper_url:
        raise ValueError("POLY_PAPER_URL not set in environment")
    if not poly_paper_account_id:
        raise ValueError("POLY_PAPER_ACCOUNT_ID not set in environment")
    
    # Build request payload
    payload = {
        "account_id": poly_paper_account_id,
        "token_id": token_id,
        "thesis": thesis,
        "thesis_probability": thesis_probability,
        "entry_max_price": entry_max_price,
        # Hardcoded risk management fields
        "entry_min_implied_edge": DEFAULT_ENTRY_MIN_IMPLIED_EDGE,
        "entry_max_capital_risk": DEFAULT_ENTRY_MAX_CAPITAL_RISK,
        "entry_max_position_shares": DEFAULT_ENTRY_MAX_POSITION_SHARES,
        # Exit conditions
        "exit_take_profit_price": exit_take_profit_price,
        "exit_stop_loss_price": exit_stop_loss_price,
    }
    
    # Add optional fields if provided
    if exit_time_stop_utc is not None:
        payload["exit_time_stop_utc"] = exit_time_stop_utc
    if valid_until_utc is not None:
        payload["valid_until_utc"] = valid_until_utc
    if notes is not None:
        payload["notes"] = notes
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{poly_paper_url.rstrip('/')}/strategies",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
    
    return data


async def update_strategy(
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
    """Update an existing trading strategy when new information changes the thesis.
    
    This uses an immutable update pattern:
    1. Finds the existing strategy by strategy_id
    2. Expires it by setting valid_until_utc to now
    3. Creates a new strategy with updated values and a new ID
    
    Use this tool when new information emerges that changes your probability estimate
    or other parameters of an existing strategy.
    
    Args:
        strategy_id (str): The ID of the strategy to update.
        thesis (str, optional): Updated evidence-based explanation of why this trade 
            should have positive expected value.
        thesis_probability (float, optional): Updated estimated probability that this 
            outcome occurs (between 0.0 and 1.0, e.g., 0.68 for 68%).
        entry_max_price (float, optional): Updated maximum price to enter position 
            (between 0.0 and 1.0).
        exit_take_profit_price (float, optional): Updated price to take profit and exit 
            (between 0.0 and 1.0).
        exit_stop_loss_price (float, optional): Updated price to cut losses and exit 
            (between 0.0 and 1.0).
        exit_time_stop_utc (str, optional): Updated ISO 8601 datetime string for 
            time-based exit (e.g., "2025-12-31T23:59:59Z").
        valid_until_utc (str, optional): Updated ISO 8601 datetime string for when 
            strategy expires (e.g., "2025-12-31T23:59:59Z").
        notes (str, optional): Updated notes or context for this strategy.
    
    Returns:
        dict: Contains:
            - old_strategy_id (str): The ID of the expired strategy
            - new_strategy (dict): The newly created strategy with updated values
    """
    poly_paper_url = os.getenv("POLY_PAPER_URL")
    
    if not poly_paper_url:
        raise ValueError("POLY_PAPER_URL not set in environment")
    
    # Build request payload with only provided fields
    payload = {"strategy_id": strategy_id}
    
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
    
    return data

