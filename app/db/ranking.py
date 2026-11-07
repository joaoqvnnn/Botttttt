from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order, OrderItem
from app.models.user import User
from app.models.wallet import WalletTransaction


async def top_products_sold(session: AsyncSession, limit: int = 10):
    """TOP 10 produtos mais vendidos (soma de quantidade em order_items)."""
    result = await session.execute(
        select(
            OrderItem.product_name,
            func.sum(OrderItem.quantity).label("total"),
        )
        .group_by(OrderItem.product_id, OrderItem.product_name)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(limit)
    )
    return result.all()


async def top_recharges_count(session: AsyncSession, limit: int = 10):
    """TOP 10 usuários com mais recargas confirmadas (quantidade)."""
    result = await session.execute(
        select(
            User.first_name,
            User.username,
            func.count(WalletTransaction.id).label("total"),
        )
        .join(WalletTransaction, WalletTransaction.user_id == User.id)
        .where(
            WalletTransaction.category == "recharge",
            WalletTransaction.type == "credit",
        )
        .group_by(User.id)
        .order_by(func.count(WalletTransaction.id).desc())
        .limit(limit)
    )
    return result.all()


async def top_purchases_count(session: AsyncSession, limit: int = 10):
    """TOP 10 usuários com mais compras realizadas (quantidade de pedidos)."""
    result = await session.execute(
        select(
            User.first_name,
            User.username,
            func.count(Order.id).label("total"),
        )
        .join(Order, Order.user_id == User.id)
        .group_by(User.id)
        .order_by(func.count(Order.id).desc())
        .limit(limit)
    )
    return result.all()


async def top_balance(session: AsyncSession, limit: int = 10):
    """TOP 10 usuários com maior saldo disponível."""
    result = await session.execute(
        select(User.first_name, User.username, User.balance)
        .order_by(User.balance.desc())
        .limit(limit)
    )
    return result.all()


async def top_depositors(session: AsyncSession, limit: int = 10):
    """TOP 10 usuários com maior volume de depósitos (soma de valores)."""
    result = await session.execute(
        select(
            User.first_name,
            User.username,
            func.sum(WalletTransaction.amount).label("total"),
        )
        .join(WalletTransaction, WalletTransaction.user_id == User.id)
        .where(
            WalletTransaction.category == "recharge",
            WalletTransaction.type == "credit",
        )
        .group_by(User.id)
        .order_by(func.sum(WalletTransaction.amount).desc())
        .limit(limit)
    )
    return result.all()


async def top_referrers(session: AsyncSession, limit: int = 10):
    """TOP 10 usuários com mais indicações válidas (via users.referred_by)."""
    referred = (
        select(User.referred_by, func.count().label("total"))
        .where(User.referred_by.isnot(None))
        .group_by(User.referred_by)
        .subquery()
    )
    result = await session.execute(
        select(User.first_name, User.username, referred.c.total)
        .join(referred, User.telegram_id == referred.c.referred_by)
        .order_by(referred.c.total.desc())
        .limit(limit)
    )
    return result.all()
