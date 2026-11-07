from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

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


async def count_available_credentials(session: AsyncSession, product_id: int) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(ProductCredential)
        .where(
            ProductCredential.product_id == product_id,
            ProductCredential.status == "available",
        )
    )
    return int(result.scalar() or 0)


async def execute_purchase(
    session: AsyncSession, user_id: int, product_id: int, quantity: int = 1
) -> dict:
    """
    Compra atômica:
      • Lock pessimista em user, product e credenciais
      • Revalida saldo e estoque
      • Cobra uma única vez, entrega credenciais, registra histórico
    """
    # 1. Lock do usuário
    user_q = await session.execute(
        select(User).where(User.id == user_id).with_for_update()
    )
    user = user_q.scalar_one_or_none()
    if user is None:
        raise ValueError("User not found")

    # 2. Lock do produto
    product_q = await session.execute(
        select(Product).where(Product.id == product_id).with_for_update()
    )
    product = product_q.scalar_one_or_none()
    if product is None or not product.is_active:
        raise OutOfStock()

    total = product.price * Decimal(quantity)

    # 3. Revalidação de saldo
    if user.balance < total:
        needed = total - user.balance
        current = user.balance
        raise InsufficientBalance(needed=needed, current=current)

    # 4. Revalidação de estoque
    if product.stock < quantity:
        raise OutOfStock()

    # 5. Reivindica credenciais (skip_locked evita deadlock entre compradores)
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
        # Estoque anunciado > credenciais reais → autocorrige para 0
        product.stock = 0
        await session.commit()
        raise NoCredentials()

    # ── A partir daqui, só executa se todas as validações passarem ──
    balance_before = user.balance
    user.balance = user.balance - total

    now = datetime.utcnow()

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

    return {
        "order_id": order.id,
        "product_name": product.name,
        "quantity": quantity,
        "unit_price": float(product.price),
        "total": float(total),
        "balance_after": float(user.balance),
        "deliveries": deliveries_data,
        "purchased_at": now,
    }
