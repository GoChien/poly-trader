import json
import logging

import httpx


async def list_events(limit: int, offset: int):
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

    # Extract and format relevant information
    formatted_events = []
    for event in events:
        # Parse markets if it's a JSON string
        markets = event.get("markets")
        if isinstance(markets, str):
            markets = json.loads(markets)

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


def get_market_price(token_id: str, side: str) -> float:
    """ Get the current market price for a given token ID and side.
    Args:
        token_id (str): The token ID of the market and side you are querying.
        side (str): The side of the market, either "BUY" or "SELL".
    Returns:
        float: The current market price.
    """
    logging.info(f"get_market_price for token_id: {token_id} on side: {side}")
    return 100.5


def place_order(price: float, size: int, token_id: str, side: str) -> bool:
    """ Place an order on the Polymarket.
    Args:
        price (float): The limit price you wish to trade.
        size (int): Quantity of shares you wish to trade.
        token_id (str): The token ID of the market and side you are trading.
        side (Side): The side of the order, either "BUY" or "SELL".
    Returns:
        bool: True if the order was placed successfully, False otherwise.
    """
    logging.info(
        f"place_order for token_id: {token_id} on side: {side} with size: {size} at price: {price}")
    return True
