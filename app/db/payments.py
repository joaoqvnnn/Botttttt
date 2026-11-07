from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.payment import Payment
from app.models.user import User
from app.models.wallet import WalletTransaction


async def create_payment_record(
    session: AsyncSession,
    user_id: int,
    amount: Decimal,
    bonus_amount: Decimal,
    expires_at: datetime | None,
) -> Payment:
    payment = Payment(
        user_id=user_id,
        amount=amount,
        bonus_amount=bonus_amount,
        status="pending",
        expires_at=expires_at,
    )
    session.add(payment)
    await session.commit()
    await session.refresh(payment)
    return payment


async def attach_mp_data(
    session: AsyncSession,
    payment_id: int,
    mp_payment_id: int,
    qr_code: str | None,
    qr_code_base64: str | None,
    ticket_url: str | None,
) -> Payment | None:
    result = await session.execute(
        select(Payment).where(Payment.id == payment_id)
    )
    payment = result.scalar_one_or_none()
    if payment is None:
        return None
    payment.mp_payment_id = mp_payment_id
    payment.qr_code = qr_code
    payment.qr_code_base64 = qr_code_base64
    payment.ticket_url = ticket_url
    await session.commit()
    await session.refresh(payment)
    return payment


async def get_payment_by_mp_id(
    session: AsyncSession, mp_payment_id: int
) -> Payment | None:
    result = await session.execute(
        select(Payment).where(Payment.mp_payment_id == mp_payment_id)
    )
    return result.scalar_one_or_none()


async def get_payment_by_id(
    session: AsyncSession, payment_id: int
) -> Payment | None:
    result = await session.execute(
        select(Payment).where(Payment.id == payment_id)
    )
    return result.scalar_one_or_none()


async def confirm_payment(
    session: AsyncSession, payment: Payment
) -> tuple[User | None, Decimal]:
    """
    Credita o saldo uma ÚNICA vez (idempotente).
    Retorna (user, total_credited). Se já estava confirmado, retorna (None, 0).
    """
    if payment.status == "approved":
        return None, Decimal("0.00")

    user_q = await session.execute(
        select(User).where(User.id == payment.user_id).with_for_update()
    )
    user = user_q.scalar_one_or_none()
    if user is None:
        return None, Decimal("0.00")

    total_credited = payment.amount + payment.bonus_amount
    balance_before = user.balance
    user.balance = user.balance + total_credited

    now = datetime.utcnow()
    payment.status = "approved"
    payment.confirmed_at = now
    payment.total_credited = total_credited

    session.add(
        WalletTransaction(
            user_id=user.id,
            type="credit",
            category="recharge",
            amount=payment.amount,
            balance_before=balance_before,
            balance_after=balance_before + payment.amount,
            description=f"Recarga PIX aprovada (#{payment.id})",
            reference_id=f"payment:{payment.id}",
        )
    )
    if payment.bonus_amount > 0:
        session.add(
            WalletTransaction(
                user_id=user.id,
                type="credit",
                category="bonus",
                amount=payment.bonus_amount,
                balance_before=balance_before + payment.amount,
                balance_after=user.balance,
                description=f"Bônus de recarga (#{payment.id})",
                reference_id=f"payment:{payment.id}",
            )
        )

    await session.commit()
    await session.refresh(user)
    return user, total_credited


def calculate_bonus(amount: Decimal) -> Decimal:
    percent = Decimal(str(settings.PIX_BONUS_PERCENT))
    if percent <= 0:
        return Decimal("0.00")
    return (amount * percent / Decimal("100")).quantize(Decimal("0.01"))


def payment_expiration() -> datetime:
    return datetime.utcnow() + timedelta(
        minutes=settings.PIX_EXPIRATION_MINUTES
    )
