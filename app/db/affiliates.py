import logging
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.affiliate import AffiliateRedemption, AffiliateReferral
from app.models.user import User
from app.models.wallet import WalletTransaction


logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# REGISTRO DE INDICAÇÃO
# ─────────────────────────────────────────────────────────


async def register_referral(
    session: AsyncSession, referrer_telegram_id: int, new_user: User
) -> bool:
    """
    Registra indicação (se válida). Retorna True se registrou.
    Regras:
      • Não pode indicar a si mesmo
      • Indicado não pode já ter referrer
      • Referrer precisa existir
    """
    if referrer_telegram_id == new_user.telegram_id:
        return False
    if new_user.referred_by is not None:
        return False

    ref_q = await session.execute(
        select(User).where(User.telegram_id == referrer_telegram_id)
    )
    referrer = ref_q.scalar_one_or_none()
    if referrer is None:
        return False

    # Verifica duplicidade na tabela de referrals
    dup_q = await session.execute(
        select(AffiliateReferral).where(
            AffiliateReferral.referred_id == new_user.id
        )
    )
    if dup_q.scalar_one_or_none() is not None:
        return False

    new_user.referred_by = referrer_telegram_id
    session.add(
        AffiliateReferral(
            referrer_id=referrer.id,
            referred_id=new_user.id,
            status="pending",
        )
    )
    await session.commit()
    return True


# ─────────────────────────────────────────────────────────
# CONFIRMAÇÃO AUTOMÁTICA NA 1ª COMPRA
# ─────────────────────────────────────────────────────────


async def confirm_referral_if_first_purchase(
    session: AsyncSession, buyer_user_id: int
) -> None:
    """
    Chamado após uma compra bem-sucedida.
    Se o comprador tinha indicação pendente, confirma e credita pontos ao referrer.
    Idempotente: só age se status == 'pending'.
    """
    try:
        ref_q = await session.execute(
            select(AffiliateReferral)
            .where(
                AffiliateReferral.referred_id == buyer_user_id,
                AffiliateReferral.status == "pending",
            )
            .with_for_update(skip_locked=True)
        )
        referral = ref_q.scalar_one_or_none()
        if referral is None:
            return

        referrer_q = await session.execute(
            select(User).where(User.id == referral.referrer_id)
        )
        referrer = referrer_q.scalar_one_or_none()
        if referrer is None:
            return

        referral.status = "confirmed"
        referral.confirmed_at = datetime.utcnow()
        referral.points_awarded = settings.AFFILIATE_POINTS_PER_REFERRAL
        referrer.referral_points = (
            referrer.referral_points or 0
        ) + settings.AFFILIATE_POINTS_PER_REFERRAL

        await session.commit()
        logger.info(
            f"Referral confirmado: user {buyer_user_id} → "
            f"referrer {referrer.id} (+{settings.AFFILIATE_POINTS_PER_REFERRAL} pts)"
        )
    except Exception:
        logger.exception("Falha ao confirmar referral")
        await session.rollback()


# ─────────────────────────────────────────────────────────
# ESTATÍSTICAS
# ─────────────────────────────────────────────────────────


async def get_user_affiliate_stats(
    session: AsyncSession, user_id: int
) -> dict:
    # Dados básicos do usuário
    user_q = await session.execute(select(User).where(User.id == user_id))
    user = user_q.scalar_one()

    # Total de indicados / confirmados / pendentes
    total_q = await session.execute(
        select(func.count())
        .select_from(AffiliateReferral)
        .where(AffiliateReferral.referrer_id == user_id)
    )
    total_indicados = int(total_q.scalar() or 0)

    confirmed_q = await session.execute(
        select(func.count())
        .select_from(AffiliateReferral)
        .where(
            AffiliateReferral.referrer_id == user_id,
            AffiliateReferral.status == "confirmed",
        )
    )
    confirmados = int(confirmed_q.scalar() or 0)
    pendentes = total_indicados - confirmados

    # Pontos recebidos (histórico) = soma de points_awarded
    awarded_q = await session.execute(
        select(func.coalesce(func.sum(AffiliateReferral.points_awarded), 0))
        .where(
            AffiliateReferral.referrer_id == user_id,
            AffiliateReferral.status == "confirmed",
        )
    )
    pontos_recebidos = int(awarded_q.scalar() or 0)

    # Redenções
    red_q = await session.execute(
        select(
            func.coalesce(func.sum(AffiliateRedemption.points_used), 0),
            func.coalesce(func.sum(AffiliateRedemption.amount_credited), 0),
        ).where(AffiliateRedemption.user_id == user_id)
    )
    row = red_q.one()
    pontos_convertidos = int(row[0] or 0)
    saldo_recebido = Decimal(row[1] or 0)

    points_current = int(user.referral_points or 0)
    conversion = Decimal(str(settings.AFFILIATE_CONVERSION_RATE))
    valor_resgate = (Decimal(points_current) * conversion).quantize(
        Decimal("0.01")
    )
    taxa = (
        round((confirmados / total_indicados) * 100, 1)
        if total_indicados > 0
        else 0.0
    )

    return {
        "pontos": points_current,
        "pontos_recebidos": pontos_recebidos,
        "pontos_convertidos": pontos_convertidos,
        "valor_resgate": float(valor_resgate),
        "saldo_recebido": float(saldo_recebido),
        "total_indicados": total_indicados,
        "confirmados": confirmados,
        "pendentes": pendentes,
        "taxa_conversao": taxa,
        "balance": float(user.balance),
    }


# ─────────────────────────────────────────────────────────
# INDICADOS PAGINADOS
# ─────────────────────────────────────────────────────────


async def get_user_referrals_paginated(
    session: AsyncSession, referrer_user_id: int, page: int, per_page: int
) -> tuple[list, int, int, int]:
    base = (
        select(AffiliateReferral, User)
        .join(User, AffiliateReferral.referred_id == User.id)
        .where(AffiliateReferral.referrer_id == referrer_user_id)
    )

    total_q = await session.execute(
        select(func.count()).select_from(
            base.with_only_columns(AffiliateReferral.id).subquery()
        )
    )
    total = int(total_q.scalar() or 0)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * per_page

    result = await session.execute(
        base.order_by(AffiliateReferral.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    items = list(result.all())
    return items, total, total_pages, page


# ─────────────────────────────────────────────────────────
# TROCA DE PONTOS
# ─────────────────────────────────────────────────────────


class RedemptionError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


async def redeem_points(
    session: AsyncSession, user_id: int, points_to_use: int
) -> dict:
    """
    Converte pontos em saldo. Validações + transação atômica.
    """
    if points_to_use <= 0:
        raise RedemptionError("invalid", "Quantidade inválida.")

    user_q = await session.execute(
        select(User).where(User.id == user_id).with_for_update()
    )
    user = user_q.scalar_one_or_none()
    if user is None:
        raise RedemptionError("not_found", "Usuário não encontrado.")

    available = int(user.referral_points or 0)
    if points_to_use > available:
        raise RedemptionError(
            "insufficient_points",
            f"Você possui apenas {available} pontos.",
        )
    if points_to_use < settings.AFFILIATE_MIN_REDEEM:
        raise RedemptionError(
            "below_min",
            f"Mínimo para resgate: {settings.AFFILIATE_MIN_REDEEM} pontos.",
        )

    conversion = Decimal(str(settings.AFFILIATE_CONVERSION_RATE))
    amount = (Decimal(points_to_use) * conversion).quantize(Decimal("0.01"))
    if amount <= 0:
        raise RedemptionError("invalid", "Valor calculado inválido.")

    balance_before = user.balance
    user.referral_points = available - points_to_use
    user.balance = balance_before + amount

    tx = WalletTransaction(
        user_id=user.id,
        type="credit",
        category="affiliate",
        amount=amount,
        balance_before=balance_before,
        balance_after=user.balance,
        description=f"Troca de {points_to_use} pontos de afiliados",
        reference_id=f"affiliate:{points_to_use}",
    )
    session.add(tx)
    await session.flush()

    redemption = AffiliateRedemption(
        user_id=user.id,
        points_used=points_to_use,
        amount_credited=amount,
        wallet_transaction_id=tx.id,
    )
    session.add(redemption)
    await session.commit()
    await session.refresh(redemption)

    return {
        "redemption_id": redemption.id,
        "points_used": points_to_use,
        "amount_credited": float(amount),
        "new_balance": float(user.balance),
        "new_points": int(user.referral_points or 0),
    }
