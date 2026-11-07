from datetime import datetime, timedelta
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.delivery import Delivery
from app.models.order import Order
from app.models.product import Product
from app.models.user import User


def compute_status(delivery: Delivery) -> str:
    """Ativa / Expirada / Finalizada."""
    if delivery.status == "finished":
        return "finalizada"
    if delivery.expires_at is None:
        return "ativa"
    if delivery.expires_at > datetime.utcnow():
        return "ativa"
    return "expirada"


async def get_user_subscriptions_paginated(
    session: AsyncSession, user_id: int, page: int, per_page: int
) -> tuple[list[tuple[Delivery, Product, Order]], dict, int, int]:
    """
    Retorna (itens, stats, total_pages, page_atual).
    Cada item = (delivery, product, order).
    """
    base = (
        select(Delivery, Product, Order)
        .join(Product, Delivery.product_id == Product.id)
        .join(Order, Delivery.order_id == Order.id)
        .where(Order.user_id == user_id)
    )

    total_q = await session.execute(
        select(func.count()).select_from(
            base.with_only_columns(Delivery.id).subquery()
        )
    )
    total = int(total_q.scalar() or 0)
    total_pages = max(1, (total + per_page - 1) // per_page)

    page = max(1, min(page, total_pages))
    offset = (page - 1) * per_page

    result = await session.execute(
        base.order_by(Delivery.id.desc()).offset(offset).limit(per_page)
    )
    items = list(result.all())

    # Estatísticas gerais do usuário
    all_q = await session.execute(
        select(Delivery)
        .join(Order, Delivery.order_id == Order.id)
        .where(Order.user_id == user_id)
    )
    all_deliveries = list(all_q.scalars().all())

    stats = {
        "total": len(all_deliveries),
        "ativas": sum(1 for d in all_deliveries if compute_status(d) == "ativa"),
        "finalizadas": sum(
            1 for d in all_deliveries
            if compute_status(d) in ("finalizada", "expirada")
        ),
    }
    return items, stats, total_pages, page


async def get_subscription_details(
    session: AsyncSession, user_id: int, delivery_id: int
) -> tuple[Delivery, Product, Order] | None:
    result = await session.execute(
        select(Delivery, Product, Order)
        .join(Product, Delivery.product_id == Product.id)
        .join(Order, Delivery.order_id == Order.id)
        .where(Delivery.id == delivery_id, Order.user_id == user_id)
    )
    row = result.first()
    return tuple(row) if row else None
