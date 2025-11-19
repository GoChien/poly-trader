import asyncio
import json
import logging
import os
import httpx

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import BalanceAllowanceParams, AssetType, OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL


def format_events(events: list[dict]) -> list[dict]:
    formatted_events = []
    for event in events:
        # Parse markets if it's a JSON string
        markets = event.get("markets")
        if isinstance(markets, str):
            markets = json.loads(markets)
        if not markets:
            continue

        formatted_markets = []
        for market in markets:
            # Parse outcomes if it's a JSON string
            outcomes = market.get("outcomes")
            if isinstance(outcomes, str):
                outcomes = json.loads(outcomes)

            # Parse outcome_prices if it's a JSON string
            outcome_prices = market.get("outcomePrices")
            if isinstance(outcome_prices, str):
                outcome_prices = json.loads(outcome_prices)
            # If outcome_prices is None, set it to an empty list.
            if not outcome_prices:
                outcome_prices = []

            # Parse token_ids if it's a JSON string
            token_ids = market.get("clobTokenIds")
            if isinstance(token_ids, str):
                token_ids = json.loads(token_ids)

            formatted_market = {
                "market_slug": market.get("slug"),
                "question": market.get("question"),
                "description": market.get("description"),
                "market_volume": market.get("volumeNum"),
                "market_volume_24hr": market.get("volume24hr"),
                "outcomes": {
                    outcome: {"price": price, "token_id": token_id}
                    for outcome, price, token_id in zip(outcomes, outcome_prices, token_ids)
                },
            }
            formatted_markets.append(formatted_market)

        formatted_event = {
            "event_slug": event.get("slug"),
            "title": event.get("title"),
            "subtitle": event.get("subtitle"),
            "event_description": event.get("description"),
            "event_volume": event.get("volumeNum"),
            "category": event.get("category"),
            "end_date": event.get("endDate"),
            "markets": formatted_markets,
        }
        formatted_events.append(formatted_event)

    return formatted_events


async def list_events(limit: int, offset: int) -> list[dict]:
    """ List popular events that are being traded on Polymarket.

    Each event contains multiple markets. Each market has 2 outcomes (e.g., YES/NO).
    Args:
        limit (int): The maximum number of events to return.
        offset (int): The number of events to skip before starting to collect the result set. Used for pagination.
    Returns:
        list[dict]: A list of event dictionaries. Including the event_slug (used to unique identify the event), the question of this event, description, markets (with their prices and token IDs), volume, category, and end_date.
    """
    base_url = "https://gamma-api.polymarket.com/events"

    # Query parameters to get top markets by volume
    params = {
        "limit": limit,
        "offset": offset,
        "order": "volume",
        "ascending": "false",  # Highest volume first
        "closed": "false",  # Only active markets
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(base_url, params=params)
        response.raise_for_status()
        events = response.json()

    return format_events(events)


async def search_events_and_markets(search_query: str, page: int) -> list[dict]:
    """ Search for events and markets on Polymarket by a free-form query string.
    Args:
        search_query (str): The free-form query string to search.
        page (int): The search result page number to return (starting from 0).
    Returns:
        list[dict]: A list of event dictionaries. Including the event_slug (used to unique identify the event), the question of this event, description, markets (with their prices and token IDs), volume, category, and end_date.
    """
    base_url = "https://gamma-api.polymarket.com/public-search"

    params = {
        "q": search_query,
        "page": page,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(base_url, params=params)
        response.raise_for_status()
        search_results = response.json()

    events = search_results.get("events")
    if isinstance(events, str):
        events = json.loads(events)
    if not events:
        return []
    return format_events(events)


async def place_order(market_slug: str, outcome: str, side: str, price: float, size: int) -> dict:
    """ Place a limit order on Polymarket with Good-Til-Cancelled (GTC) duration.
    
    This will place a limit order that remains active until it is filled or manually cancelled.
    The order will only execute at the specified price or better.
    
    Args:
        market_slug (str): The slug (i.e. the unique identifier) of the market you are trading on.
        outcome (str): The outcome you are trading (e.g., "YES" or "NO").
        side (str): The side of the order, either "BUY" or "SELL".
        price (float): The limit price for your order (between 0.0 and 1.0). For BUY orders, the order will execute at this price or lower. For SELL orders, the order will execute at this price or higher.
        size (int): Quantity of shares you wish to trade.
    Returns:
        dict: A dictionary containing:
            - success (bool): Whether the order was placed successfully
            - order_id (str): The order ID if successful
            - price (float): The price at which the order was placed
            - size_requested (float): The number of shares requested
            - message (str): Success or error message
            - response (dict): Full response from the API if successful
    """
    logging.info(
        f"place_limit_order (GTC) on market_slug: {market_slug}, outcome: {outcome}, side: {side}, price: {price}, size: {size}")
    
    try:
        # Step 1: Get market details to obtain token_id
        base_url = f"https://gamma-api.polymarket.com/markets/slug/{market_slug}"
        
        async with httpx.AsyncClient(timeout=30.0) as http_client:
            response = await http_client.get(base_url)
            response.raise_for_status()
            market_data = response.json()
        
        # Parse market data to get token_id
        outcomes = market_data.get("outcomes")
        if isinstance(outcomes, str):
            outcomes = json.loads(outcomes)
        
        token_ids = market_data.get("clobTokenIds")
        if isinstance(token_ids, str):
            token_ids = json.loads(token_ids)
        
        # Find the token_id for the specified outcome
        token_id = None
        for i, out in enumerate(outcomes):
            if out.upper() == outcome.upper():
                token_id = token_ids[i]
                break
        
        if not token_id:
            error_msg = f"Outcome '{outcome}' not found in market '{market_slug}'"
            logging.error(error_msg)
            return {
                "success": False,
                "order_id": None,
                "price": None,
                "size_requested": float(size),
                "message": error_msg,
                "response": None
            }
        
        logging.info(f"Found token_id: {token_id}, placing limit order at price: {price}")
        
        # Step 2: Initialize ClobClient
        HOST = "https://clob.polymarket.com"
        CHAIN_ID = 137
        PRIVATE_KEY = os.getenv("POLYMARKET_PRIVATE_KEY")
        FUNDER = os.getenv("POLYMARKET_PROXY_ADDRESS")
        
        if not PRIVATE_KEY or not FUNDER:
            error_msg = "POLYMARKET_PRIVATE_KEY or POLYMARKET_PROXY_ADDRESS not set in environment"
            logging.error(error_msg)
            return {
                "success": False,
                "order_id": None,
                "price": price,
                "size_requested": float(size),
                "message": error_msg,
                "response": None
            }
        
        client = ClobClient(
            HOST,
            key=PRIVATE_KEY,
            chain_id=CHAIN_ID,
            signature_type=1,  # 1 for email/Magic wallet, 2 for browser wallet
            funder=FUNDER
        )
        
        # Set API credentials (run in thread to avoid blocking)
        api_creds = await asyncio.to_thread(client.create_or_derive_api_creds)
        client.set_api_creds(api_creds)
        
        # Step 3: Convert side string to constant
        order_side = BUY if side.upper() == "BUY" else SELL
        
        # Step 4: Create limit order arguments with specified price
        order_args = OrderArgs(
            price=price,
            size=float(size),
            side=order_side,
            token_id=token_id,
        )
        
        # Step 5: Sign the order (run in thread to avoid blocking)
        signed_order = await asyncio.to_thread(client.create_order, order_args)
        
        # Step 6: Post the order as GTC (Good-Till-Cancelled) (run in thread to avoid blocking)
        resp = await asyncio.to_thread(client.post_order, signed_order, OrderType.GTC)
        
        logging.info(f"Limit order (GTC) placed successfully: {resp}")
        
        # Extract order details from response
        order_id = resp.get("orderID") if isinstance(resp, dict) else None
        
        return {
            "success": True,
            "order_id": order_id,
            "price": price,
            "size_requested": float(size),
            "message": "Limit order (GTC) placed successfully",
            "response": resp
        }
        
    except Exception as e:
        error_msg = f"Error placing order: {e}"
        logging.error(error_msg)
        return {
            "success": False,
            "order_id": None,
            "price": None,
            "size_requested": float(size),
            "message": error_msg,
            "response": None
        }


async def cancel_order(order_id: str) -> dict:
    """ Cancel a single order on Polymarket.
    
    Args:
        order_id (str): The ID of the order to cancel.
    Returns:
        dict: A dictionary containing:
            - success (bool): Whether the order was cancelled successfully
            - canceled (list): List of canceled order IDs
            - not_canceled (dict): Order ID to reason map for orders that couldn't be canceled
            - message (str): Success or error message
            - response (dict): Full response from the API if successful
    """
    logging.info(f"Canceling order: {order_id}")
    
    try:
        # Initialize ClobClient
        HOST = "https://clob.polymarket.com"
        CHAIN_ID = 137
        PRIVATE_KEY = os.getenv("POLYMARKET_PRIVATE_KEY")
        FUNDER = os.getenv("POLYMARKET_PROXY_ADDRESS")
        
        if not PRIVATE_KEY or not FUNDER:
            error_msg = "POLYMARKET_PRIVATE_KEY or POLYMARKET_PROXY_ADDRESS not set in environment"
            logging.error(error_msg)
            return {
                "success": False,
                "canceled": [],
                "not_canceled": {},
                "message": error_msg,
                "response": None
            }
        
        client = ClobClient(
            HOST,
            key=PRIVATE_KEY,
            chain_id=CHAIN_ID,
            signature_type=1,  # 1 for email/Magic wallet, 2 for browser wallet
            funder=FUNDER
        )
        
        # Set API credentials (run in thread to avoid blocking)
        api_creds = await asyncio.to_thread(client.create_or_derive_api_creds)
        client.set_api_creds(api_creds)
        
        # Cancel the order (run in thread to avoid blocking)
        resp = await asyncio.to_thread(client.cancel, order_id)
        
        logging.info(f"Order cancellation response: {resp}")
        
        # Extract response details
        canceled = resp.get("canceled", []) if isinstance(resp, dict) else []
        not_canceled = resp.get("not_canceled", {}) if isinstance(resp, dict) else {}
        
        # Determine success based on whether the order was canceled
        success = len(canceled) > 0 or (len(not_canceled) == 0 and isinstance(resp, dict))
        
        return {
            "success": success,
            "canceled": canceled,
            "not_canceled": not_canceled,
            "message": "Order cancelled successfully" if success else "Failed to cancel order",
            "response": resp
        }
        
    except Exception as e:
        error_msg = f"Error canceling order: {e}"
        logging.error(error_msg)
        return {
            "success": False,
            "canceled": [],
            "not_canceled": {},
            "message": error_msg,
            "response": None
        }


