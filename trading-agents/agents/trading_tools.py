import json
import logging

import httpx


async def list_markets(limit: int, offset: int):
    """ List available markets on Polymarket (order by popularity).

    Args:
        limit (int): The maximum number of markets to return.
        offset (int): The number of markets to skip before starting to collect the result set. Used for pagination.
    Returns:
        list[dict]: A list of market dictionaries.
    """
    base_url = "https://gamma-api.polymarket.com/markets"

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
        markets = response.json()

    # Extract and format relevant information
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

        # Parse token_ids if it's a JSON string
        token_ids = market.get("clobTokenIds")
        if isinstance(token_ids, str):
            token_ids = json.loads(token_ids)

        formatted_market = {
            "question": market.get("question"),
            "description": market.get("description"),
            "outcomes": {
                outcome: {"price": price, "token_id": token_id}
                for outcome, price, token_id in zip(outcomes, outcome_prices, token_ids)
            },
            "volume": market.get("volumeNum"),
            "volume_24hr": market.get("volume24hr"),
            "market_id": market.get("slug"),
            "category": market.get("category"),
            "end_date": market.get("endDate"),
        }
        formatted_markets.append(formatted_market)

    return formatted_markets


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
