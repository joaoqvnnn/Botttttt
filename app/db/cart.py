from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cart import CartItem


async def add_to_cart(
    session: AsyncSession, user_id: int, product_id: int, quantity: int = 1
) -> int:
    """
    Adiciona/incrementa produto no carrinho.
    Retorna o total de itens (soma de quantidades) no carrinho do usuário.
    """
    existing_q = await session.execute(
        select(CartItem).where(
            CartItem.user_id == user_id,
            CartItem.product_id == product_id,
        )
    )
    item = existing_q.scalar_one_or_none()

    if item is not None:
        item.quantity += quantity
    else:
        session.add(
            CartItem(user_id=user_id, product_id=product_id, quantity=quantity)
        )
    await session.commit()

    return await get_cart_count(session, user_id)


async def get_cart_count(session: AsyncSession, user_id: int) -> int:
    result = await session.execute(
        select(func.coalesce(func.sum(CartItem.quantity), 0)).where(
            CartItem.user_id == user_id
        )
    )
    return int(result.scalar() or 0)


async def get_cart_items(session: AsyncSession, user_id: int) -> list[CartItem]:
    result = await session.execute(
        select(CartItem)
        .where(CartItem.user_id == user_id)
        .order_by(CartItem.created_at.asc())
    )
    return list(result.scalars().all())
