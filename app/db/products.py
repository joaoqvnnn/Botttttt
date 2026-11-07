from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product, ProductView


async def get_active_products_paginated(
    session: AsyncSession, page: int, per_page: int
) -> tuple[list[Product], int, int]:
    """
    Retorna (produtos, total_paginas, pagina_atual).
    Corrige a página se estiver fora dos limites.
    """
    total_q = await session.execute(
        select(func.count()).select_from(Product).where(Product.is_active.is_(True))
    )
    total = int(total_q.scalar() or 0)
    total_pages = max(1, (total + per_page - 1) // per_page)

    page = max(1, min(page, total_pages))
    offset = (page - 1) * per_page

    result = await session.execute(
        select(Product)
        .where(Product.is_active.is_(True))
        .order_by(Product.id.asc())
        .offset(offset)
        .limit(per_page)
    )
    products = list(result.scalars().all())
    return products, total_pages, page


async def get_product(session: AsyncSession, product_id: int) -> Product | None:
    result = await session.execute(
        select(Product).where(Product.id == product_id)
    )
    return result.scalar_one_or_none()


async def register_view_and_get_counters(
    session: AsyncSession, product_id: int, user_id: int
) -> int:
    """
    Registra/atualiza a visualização do usuário no produto
    e retorna a quantidade de usuários distintos visualizando nos últimos 5 minutos.
    """
    now = datetime.utcnow()

    existing_q = await session.execute(
        select(ProductView).where(
            ProductView.product_id == product_id,
            ProductView.user_id == user_id,
        )
    )
    view = existing_q.scalar_one_or_none()

    if view is not None:
        view.viewed_at = now
    else:
        session.add(
            ProductView(product_id=product_id, user_id=user_id, viewed_at=now)
        )
    await session.commit()

    cutoff = now - timedelta(minutes=5)
    count_q = await session.execute(
        select(func.count(func.distinct(ProductView.user_id))).where(
            ProductView.product_id == product_id,
            ProductView.viewed_at >= cutoff,
        )
    )
    viewers = int(count_q.scalar() or 0)
    return max(viewers, 1)


async def get_product_price(session: AsyncSession, product_id: int) -> Decimal | None:
    product = await get_product(session, product_id)
    return product.price if product else None
