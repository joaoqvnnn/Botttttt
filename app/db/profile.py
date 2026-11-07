from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order
from app.models.user import User
from app.models.wallet import WalletTransaction


async def get_profile_stats(session: AsyncSession, user_id: int) -> dict:
    # Compras
    orders_q = await session.execute(
        select(func.count()).select_from(Order).where(Order.user_id == user_id)
    )
    total_compras = int(orders_q.scalar() or 0)

    # Total em recargas (credits da categoria recharge)
    recharge_q = await session.execute(
        select(func.coalesce(func.sum(WalletTransaction.amount), 0)).where(
            WalletTransaction.user_id == user_id,
            WalletTransaction.type == "credit",
            WalletTransaction.category == "recharge",
        )
    )
    total_recargas = Decimal(recharge_q.scalar() or 0)

    # Gift cards resgatados
    gift_q = await session.execute(
        select(func.coalesce(func.sum(WalletTransaction.amount), 0)).where(
            WalletTransaction.user_id == user_id,
            WalletTransaction.type == "credit",
            WalletTransaction.category == "gift",
        )
    )
    total_gifts = Decimal(gift_q.scalar() or 0)

    # Saques (category = withdraw, type = debit)
    withdraw_q = await session.execute(
        select(func.coalesce(func.sum(WalletTransaction.amount), 0)).where(
            WalletTransaction.user_id == user_id,
            WalletTransaction.type == "debit",
            WalletTransaction.category == "withdraw",
        )
    )
    total_saques = Decimal(withdraw_q.scalar() or 0)

    # Indicações
    user_q = await session.execute(
        select(User).where(User.id == user_id)
    )
    user = user_q.scalar_one()

    indicados_q = await session.execute(
        select(func.count()).select_from(User).where(
            User.referred_by == user.telegram_id
        )
    )
    total_indicados = int(indicados_q.scalar() or 0)

    return {
        "saldo": float(user.balance),
        "total_compras": total_compras,
        "total_recargas": float(total_recargas),
        "total_gifts": float(total_gifts),
        "total_saques": float(total_saques),
        "pontos_indicacao": int(user.referral_points or 0),
        "total_indicados": total_indicados,
    }


async def get_user_transactions(
    session: AsyncSession, user_id: int, limit: int = 200
) -> list[WalletTransaction]:
    result = await session.execute(
        select(WalletTransaction)
        .where(WalletTransaction.user_id == user_id)
        .order_by(WalletTransaction.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
