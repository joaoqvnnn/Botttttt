from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cart import CartItem
from app.models.delivery import Delivery, ProductCredential
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.user import User
from app.models.wallet import WalletTransaction


class InsufficientBalance(Exception):
    def __init__(self, needed: Decimal, current: Decimal):
        self.needed = needed
        self.current = current
        super().__init__("Saldo insuficiente")


class OutOfStock(Exception):
    pass


class NoCredentials(Exception):
    pass


def _compute_expires_at(product: Product, now: datetime) -> datetime | None:
    if product.duration_days and product.duration_days > 0:
        return now + timedelta(days=product.duration_days)
    return None


async def count_available_credentials(
    session: AsyncSession, product_id: int
) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(ProductCredential)
        .where(
            ProductCredential.product_id == product_id,
            ProductCredential.status == "available",
        )
    )
    return int(result.scalar() or 0)


async def _confirm_referral_safe(user_id: int) -> None:
    """Fire-and-forget da confirmação de indicação."""
    try:
        from app.database import SessionLocal as _SL
        from app.db.affiliates import confirm_referral_if_first_purchase

        async with _SL() as s:
            await confirm_referral_if_first_purchase(s, user_id)
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "Falha ao confirmar referral pós-compra"
        )


async def execute_purchase(
    session: AsyncSession, user_id: int, product_id: int, quantity: int = 1
) -> dict:
    user_q = await session.execute(
        select(User).where(User.id == user_id).with_for_update()
    )
    user = user_q.scalar_one_or_none()
    if user is None:
        raise ValueError("User not found")

    product_q = await session.execute(
        select(Product).where(Product.id == product_id).with_for_update()
    )
    product = product_q.scalar_one_or_none()
    if product is None or not product.is_active:
        raise OutOfStock()

    total = product.price * Decimal(quantity)

    if user.balance < total:
        raise InsufficientBalance(
            needed=total - user.balance, current=user.balance
        )
    if product.stock < quantity:
        raise OutOfStock()

    cred_q = await session.execute(
        select(ProductCredential)
        .where(
            ProductCredential.product_id == product_id,
            ProductCredential.status == "available",
        )
        .order_by(ProductCredential.id.asc())
        .limit(quantity)
        .with_for_update(skip_locked=True)
    )
    credentials = list(cred_q.scalars().all())

    if len(credentials) < quantity:
        product.stock = 0
        await session.commit()
        raise NoCredentials()

    balance_before = user.balance
    user.balance = user.balance - total
    now = datetime.utcnow()
    expires_at = _compute_expires_at(product, now)

    order = Order(user_id=user_id, total=total, status="paid", paid_at=now)
    session.add(order)
    await session.flush()

    order_item = OrderItem(
        order_id=order.id,
        product_id=product.id,
        product_name=product.name,
        quantity=quantity,
        unit_price=product.price,
        total=total,
    )
    session.add(order_item)
    await session.flush()

    deliveries_data: list[dict] = []
    for cred in credentials:
        cred.status = "sold"
        cred.order_id = order.id
        cred.sold_at = now

        delivery = Delivery(
            order_id=order.id,
            order_item_id=order_item.id,
            product_id=product.id,
            credential_id=cred.id,
            email=cred.email,
            password=cred.password,
            status="active",
            expires_at=expires_at,
        )
        session.add(delivery)
        await session.flush()
        deliveries_data.append(
            {"id": delivery.id, "email": cred.email, "password": cred.password}
        )

    product.stock = product.stock - quantity

    session.add(
        WalletTransaction(
            user_id=user_id,
            type="debit",
            category="purchase",
            amount=total,
            balance_before=balance_before,
            balance_after=user.balance,
            description=f"Compra: {product.name} x{quantity}",
            reference_id=f"order:{order.id}",
        )
    )

    await session.commit()

    result = {
        "order_id": order.id,
        "product_name": product.name,
        "quantity": quantity,
        "unit_price": float(product.price),
        "total": float(total),
        "balance_after": float(user.balance),
        "deliveries": deliveries_data,
        "purchased_at": now,
    }

    await _confirm_referral_safe(user_id)
    return result


async def execute_cart_purchase(
    session: AsyncSession, user_id: int
) -> dict:
    user_q = await session.execute(
        select(User).where(User.id == user_id).with_for_update()
    )
    user = user_q.scalar_one_or_none()
    if user is None:
        raise ValueError("User not found")

    cart_q = await session.execute(
        select(CartItem)
        .where(CartItem.user_id == user_id)
        .order_by(CartItem.id.asc())
    )
    cart_items = list(cart_q.scalars().all())

    if not cart_items:
        raise ValueError("Cart empty")

    product_ids = [item.product_id for item in cart_items]
    products_q = await session.execute(
        select(Product)
        .where(Product.id.in_(product_ids))
        .order_by(Product.id.asc())
        .with_for_update()
    )
    products = {p.id: p for p in products_q.scalars().all()}

    total = Decimal("0")
    for item in cart_items:
        product = products.get(item.product_id)
        if product is None or not product.is_active:
            raise OutOfStock()
        if product.stock < item.quantity:
            raise OutOfStock()
        total += product.price * Decimal(item.quantity)

    if user.balance < total:
        raise InsufficientBalance(
            needed=total - user.balance, current=user.balance
        )

    balance_before = user.balance
    now = datetime.utcnow()

    order = Order(user_id=user_id, total=total, status="paid", paid_at=now)
    session.add(order)
    await session.flush()

    items_result: list[dict] = []

    for item in cart_items:
        product = products[item.product_id]
        item_total = product.price * Decimal(item.quantity)
        expires_at = _compute_expires_at(product, now)

        cred_q = await session.execute(
            select(ProductCredential)
            .where(
                ProductCredential.product_id == product.id,
                ProductCredential.status == "available",
            )
            .order_by(ProductCredential.id.asc())
            .limit(item.quantity)
            .with_for_update(skip_locked=True)
        )
        credentials = list(cred_q.scalars().all())

        if len(credentials) < item.quantity:
            product.stock = 0
            raise NoCredentials()

        order_item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            product_name=product.name,
            quantity=item.quantity,
            unit_price=product.price,
            total=item_total,
        )
        session.add(order_item)
        await session.flush()

        item_deliveries: list[dict] = []
        for cred in credentials:
            cred.status = "sold"
            cred.order_id = order.id
            cred.sold_at = now

            delivery = Delivery(
                order_id=order.id,
                order_item_id=order_item.id,
                product_id=product.id,
                credential_id=cred.id,
                email=cred.email,
                password=cred.password,
                status="active",
                expires_at=expires_at,
            )
            session.add(delivery)
            await session.flush()
            item_deliveries.append(
                {
                    "id": delivery.id,
                    "email": cred.email,
                    "password": cred.password,
                }
            )

        product.stock = product.stock - item.quantity

        items_result.append(
            {
                "product_id": product.id,
                "product_name": product.name,
                "quantity": item.quantity,
                "unit_price": float(product.price),
                "total": float(item_total),
                "deliveries": item_deliveries,
            }
        )

    user.balance = balance_before - total

    session.add(
        WalletTransaction(
            user_id=user_id,
            type="debit",
            category="purchase",
            amount=total,
            balance_before=balance_before,
            balance_after=user.balance,
            description=f"Compra em carrinho: {len(cart_items)} produto(s)",
            reference_id=f"order:{order.id}",
        )
    )

    for item in cart_items:
        await session.delete(item)

    await session.commit()

    result = {
        "order_id": order.id,
        "total": float(total),
        "balance_after": float(user.balance),
        "items": items_result,
        "purchased_at": now,
    }

    await _confirm_referral_safe(user_id)
    return result
