import logging


def list_markets(limit: int, offset: int) -> list[dict]:
    """ List available markets on Polymarket.
    Args:
        limit (int): The maximum number of markets to return.
        offset (int): The number of markets to skip before starting to collect the result set.
    Returns:
        list[dict]: A list of market dictionaries.
    """
    return [{"id": "123", "question": "Will Germany win the 2026 World Cup final?"}, {"id": "456", "question": "Will France win the 2026 World Cup final?"}]


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
