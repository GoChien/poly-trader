import json
import logging

import httpx


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

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(base_url, params=params)
        response.raise_for_status()
        search_results = response.json()

    events = search_results.get("events")
    if isinstance(events, str):
        events = json.loads(events)
    if not events:
        return []
    return format_events(events)


async def place_order_at_market_price(market_slug: str, outcome: str, side: str, size: int) -> bool:
    """ Place an order on the Polymarket at the current market price.
    Args:
        market_slug (str): The slug (i.e. the unique identifier) of the market you are trading on.
        outcome (str): The outcome you are trading (e.g., "YES" or "NO").
        side (str): The side of the order, either "BUY" or "SELL".
        size (int): Quantity of shares you wish to trade.
    Returns:
        bool: True if the order was placed successfully, False otherwise.
    """
    logging.info(
        f"place_order_at_market_price on market_slug: {market_slug}, outcome: {outcome}, side: {side}, size: {size}")
    return True
