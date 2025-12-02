import uuid
from decimal import Decimal

import httpx
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.account import Account
from models.order import Order, OrderSide, OrderStatus
from models.position import Position
from models.transaction import Transaction

POLYMARKET_CLOB_URL = "https://clob.polymarket.com"


class PlaceLimitOrderRequest(BaseModel):
    account_id: uuid.UUID
    price: Decimal
    size: int
    side: OrderSide
    token_id: str


class PlaceLimitOrderResponse(BaseModel):
    order_id: uuid.UUID | None = None
    transaction_id: uuid.UUID | None = None
    status: str  # "filled" or "open"
    message: str


class CancelOrderResponse(BaseModel):
    order_id: uuid.UUID
    status: str
    message: str


async def get_market_price(token_id: str, side: OrderSide) -> Decimal:
    """
    Get the current market price for a token from Polymarket CLOB API.
    
    For BUY orders, we need the ASK price (what sellers are asking).
    For SELL orders, we need the BID price (what buyers are bidding).
    """
    api_side = "BUY" if side == OrderSide.BUY else "SELL"
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{POLYMARKET_CLOB_URL}/price",
            params={"token_id": token_id, "side": api_side},
            timeout=10.0,
        )
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to get market price from Polymarket: {response.text}"
            )
        
        data = response.json()
        return Decimal(data["price"])


async def place_limit_order_handler(
    request: PlaceLimitOrderRequest, db: AsyncSession
) -> PlaceLimitOrderResponse:
    """
    Place a limit order.
    
    For BUY orders:
    - Check if there's sufficient balance
    - If limit price >= market price, fill immediately at market price
    - Otherwise, create an open order
    
    For SELL orders:
    - Check if there's sufficient shares in positions
    - If limit price <= market price, fill immediately at market price
    - Otherwise, create an open order
    """
    try:
        # Get the account
        stmt = select(Account).where(Account.account_id == request.account_id)
        result = await db.execute(stmt)
        account = result.scalar_one_or_none()
        
        if not account:
            raise HTTPException(
                status_code=404,
                detail=f"Account with id '{request.account_id}' not found"
            )
        
        # Get current market price
        market_price = await get_market_price(request.token_id, request.side)
        
        if request.side == OrderSide.BUY:
            return await _handle_buy_order(request, account, market_price, db)
        else:
            return await _handle_sell_order(request, account, market_price, db)
            
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Failed to place limit order: {str(e)}"
        )


async def _handle_buy_order(
    request: PlaceLimitOrderRequest,
    account: Account,
    market_price: Decimal,
    db: AsyncSession,
) -> PlaceLimitOrderResponse:
    """Handle BUY order logic."""
    order_cost = request.price * request.size
    
    # Check sufficient funds
    if account.balance < order_cost:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient funds. Required: {order_cost}, Available: {account.balance}"
        )
    
    # If limit price >= market price, fill immediately at market price
    if request.price >= market_price:
        execution_cost = market_price * request.size
        
        # Deduct from account balance
        account.balance -= execution_cost
        
        # Update or create position
        position = await _get_or_create_position(
            db, request.account_id, request.token_id
        )
        position.shares += request.size
        position.total_cost += execution_cost
        
        # Create transaction record
        transaction = Transaction(
            account_id=request.account_id,
            token_id=request.token_id,
            execution_price=market_price,
            side=OrderSide.BUY,
            size=request.size,
        )
        db.add(transaction)
        
        await db.commit()
        await db.refresh(transaction)
        
        return PlaceLimitOrderResponse(
            transaction_id=transaction.transaction_id,
            status="filled",
            message=f"Order filled immediately at market price {market_price}"
        )
    else:
        # Create open order (funds will be reserved when order is filled)
        order = Order(
            account_id=request.account_id,
            price=request.price,
            size=request.size,
            side=OrderSide.BUY,
            token_id=request.token_id,
            status=OrderStatus.OPEN,
        )
        db.add(order)
        await db.commit()
        await db.refresh(order)
        
        return PlaceLimitOrderResponse(
            order_id=order.order_id,
            status="open",
            message=f"Limit order created. Limit price {request.price} < market price {market_price}"
        )


async def _handle_sell_order(
    request: PlaceLimitOrderRequest,
    account: Account,
    market_price: Decimal,
    db: AsyncSession,
) -> PlaceLimitOrderResponse:
    """Handle SELL order logic."""
    # Check position for sufficient shares
    stmt = select(Position).where(
        Position.account_id == request.account_id,
        Position.token_id == request.token_id,
    )
    result = await db.execute(stmt)
    position = result.scalar_one_or_none()
    
    if not position or position.shares < request.size:
        available = position.shares if position else 0
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient shares. Required: {request.size}, Available: {available}"
        )
    
    # If limit price <= market price, fill immediately at market price
    if request.price <= market_price:
        execution_proceeds = market_price * request.size
        
        # Add to account balance
        account.balance += execution_proceeds
        
        # Update position
        # Calculate proportional cost basis to remove
        cost_per_share = position.total_cost / position.shares if position.shares > 0 else Decimal("0")
        cost_to_remove = cost_per_share * request.size
        
        position.shares -= request.size
        position.total_cost -= cost_to_remove
        
        # Create transaction record
        transaction = Transaction(
            account_id=request.account_id,
            token_id=request.token_id,
            execution_price=market_price,
            side=OrderSide.SELL,
            size=request.size,
        )
        db.add(transaction)
        
        await db.commit()
        await db.refresh(transaction)
        
        return PlaceLimitOrderResponse(
            transaction_id=transaction.transaction_id,
            status="filled",
            message=f"Order filled immediately at market price {market_price}"
        )
    else:
        # Create open order
        order = Order(
            account_id=request.account_id,
            price=request.price,
            size=request.size,
            side=OrderSide.SELL,
            token_id=request.token_id,
            status=OrderStatus.OPEN,
        )
        db.add(order)
        await db.commit()
        await db.refresh(order)
        
        return PlaceLimitOrderResponse(
            order_id=order.order_id,
            status="open",
            message=f"Limit order created. Limit price {request.price} > market price {market_price}"
        )


async def _get_or_create_position(
    db: AsyncSession, account_id: uuid.UUID, token_id: str
) -> Position:
    """Get existing position or create a new one."""
    stmt = select(Position).where(
        Position.account_id == account_id,
        Position.token_id == token_id,
    )
    result = await db.execute(stmt)
    position = result.scalar_one_or_none()
    
    if not position:
        position = Position(
            account_id=account_id,
            token_id=token_id,
            shares=0,
            total_cost=Decimal("0.00"),
        )
        db.add(position)
    
    return position


async def cancel_order_handler(
    order_id: uuid.UUID, db: AsyncSession
) -> CancelOrderResponse:
    """
    Cancel an open order.
    
    Only orders with status OPEN can be cancelled.
    """
    try:
        # Get the order
        stmt = select(Order).where(Order.order_id == order_id)
        result = await db.execute(stmt)
        order = result.scalar_one_or_none()
        
        if not order:
            raise HTTPException(
                status_code=404,
                detail=f"Order with id '{order_id}' not found"
            )
        
        # Check if order can be cancelled
        if order.status != OrderStatus.OPEN:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel order. Current status is '{order.status.value}', only OPEN orders can be cancelled"
            )
        
        # Update order status to CANCELLED
        order.status = OrderStatus.CANCELLED
        await db.commit()
        
        return CancelOrderResponse(
            order_id=order_id,
            status="cancelled",
            message="Order successfully cancelled"
        )
        
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Failed to cancel order: {str(e)}"
        )

