import os
import httpx

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import BalanceAllowanceParams, AssetType, OpenOrderParams
from py_clob_client.order_builder.constants import BUY, SELL

def get_cash_balance():
    """ Get the cash balance of the user.
    Returns:
        float: The cash balance of the user in USDC.
    """
    # Initialize your client
    HOST = "https://clob.polymarket.com"
    CHAIN_ID = 137
    PRIVATE_KEY = os.getenv("POLYMARKET_PRIVATE_KEY")
    FUNDER = os.getenv("POLYMARKET_PROXY_ADDRESS")  # Your Polymarket proxy address

    client = ClobClient(
        HOST,
        key=PRIVATE_KEY,
        chain_id=CHAIN_ID,
        signature_type=1,  # 1 for email/Magic wallet, 2 for Metamask
        funder=FUNDER
    )

    client.set_api_creds(client.create_or_derive_api_creds())

    # Get USDC balance
    result = client.get_balance_allowance(
        params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
    )
    # Convert balance to float, and divided by 10**6 to get the balance in USDC
    balance = float(result['balance']) / 10**6
    return balance


async def get_user_positions(
    limit: int = 100,
    sort_by: str = "CASHPNL",
    sort_direction: str = "DESC"
) -> list[dict]:
    """Get the current positions for a user from Polymarket.
    
    Args:
        limit (int): Maximum number of positions to return (default: 100, max: 500).
        sort_by (str): Sort positions by one of: CURRENT, INITIAL, TOKENS, CASHPNL, PERCENTPNL, 
                      TITLE, RESOLVING, PRICE, AVGPRICE (default: CASHPNL).
        sort_direction (str): Sort direction, either ASC or DESC (default: DESC).
    
    Returns:
        list[dict]: A list of position dictionaries with the following key information:
            - title: The market title
            - outcome: The outcome being traded (e.g., "YES" or "NO")
            - size: Number of shares held
            - avg_price: Average price paid per share
            - current_price: Current market price
            - initial_value: Total amount paid for the position
            - current_value: Current value of the position
            - cash_pnl: Profit/loss in dollar terms
            - percent_pnl: Profit/loss as a percentage
            - realized_pnl: Realized profit/loss from closed trades
            - end_date: When the market closes
            - slug: Market slug for trading
            - event_slug: Event slug for reference
    """
    user_address = os.getenv("POLYMARKET_PROXY_ADDRESS")
    
    if not user_address:
        raise ValueError("POLYMARKET_PROXY_ADDRESS not set in environment")
    
    base_url = "https://data-api.polymarket.com/positions"
    
    params = {
        "user": user_address,
        "limit": min(limit, 500),  # Cap at API maximum
        "sortBy": sort_by,
        "sortDirection": sort_direction,
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(base_url, params=params)
        response.raise_for_status()
        positions = response.json()
    
    # Format positions for LLM consumption
    formatted_positions = []
    for pos in positions:
        formatted_pos = {
            "title": pos.get("title", "Unknown"),
            "outcome": pos.get("outcome", "Unknown"),
            "size": pos.get("size", 0),
            "avg_price": pos.get("avgPrice", 0),
            "current_price": pos.get("curPrice", 0),
            "initial_value": pos.get("initialValue", 0),
            "current_value": pos.get("currentValue", 0),
            "cash_pnl": pos.get("cashPnl", 0),
            "percent_pnl": pos.get("percentPnl", 0),
            "realized_pnl": pos.get("realizedPnl", 0),
            "percent_realized_pnl": pos.get("percentRealizedPnl", 0),
            "total_bought": pos.get("totalBought", 0),
            "end_date": pos.get("endDate", "Unknown"),
            "slug": pos.get("slug", ""),
            "event_slug": pos.get("eventSlug", ""),
            "redeemable": pos.get("redeemable", False),
            "mergeable": pos.get("mergeable", False),
        }
        formatted_positions.append(formatted_pos)
    
    return formatted_positions


def get_active_orders() -> list[dict]:
    """Get all active orders for the user from Polymarket CLOB.
    
    This function retrieves all open/active orders that haven't been filled or cancelled yet.
    
    Returns:
        list[dict]: A list of active order dictionaries with information including:
            - order_id: The unique identifier for the order
            - market: The market condition ID
            - asset_id: The asset/token ID
            - price: The order price
            - size: The order size
            - side: BUY or SELL
            - type: Order type (GTC, FOK, GTD)
            - timestamp: When the order was created
            And other order details returned by the API
    """
    # Initialize client
    HOST = "https://clob.polymarket.com"
    CHAIN_ID = 137
    PRIVATE_KEY = os.getenv("POLYMARKET_PRIVATE_KEY")
    FUNDER = os.getenv("POLYMARKET_PROXY_ADDRESS")  # Your Polymarket proxy address

    if not PRIVATE_KEY:
        raise ValueError("POLYMARKET_PRIVATE_KEY not set in environment")
    if not FUNDER:
        raise ValueError("POLYMARKET_PROXY_ADDRESS not set in environment")

    client = ClobClient(
        HOST,
        key=PRIVATE_KEY,
        chain_id=CHAIN_ID,
        signature_type=1,  # 1 for email/Magic wallet, 2 for Metamask
        funder=FUNDER
    )

    client.set_api_creds(client.create_or_derive_api_creds())

    # Get all active orders
    orders = client.get_orders(OpenOrderParams())
    
    return orders

