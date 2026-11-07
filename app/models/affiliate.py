from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AffiliateReferral(Base):
    """Cada indicação registrada — pending até a 1ª compra do indicado."""

    __tablename__ = "affiliate_referrals"

    id: Mapped[int] = mapped_column(primary_key=True)
    referrer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    referred_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20), default="pending", index=True, nullable=False
    )  # pending | confirmed | rejected
    points_awarded: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class AffiliateRedemption(Base):
    """Cada troca de pontos por saldo."""

    __tablename__ = "affiliate_redemptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    points_used: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_credited: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False
    )
    wallet_transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("wallet_transactions.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
