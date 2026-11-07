from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text

from app.config import settings


engine = create_async_engine(settings.async_database_url, echo=False, future=True)

SessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


async def init_db() -> None:
    # Importa os models para registrar as tabelas no metadata
    from app import models  # noqa: F401

    async with engine.begin() as conn:
        # Cria as tabelas que ainda não existem
        await conn.run_sync(Base.metadata.create_all)
        
        # Atualiza tabelas que já existiam adicionando as colunas novas
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_points INTEGER DEFAULT 0 NOT NULL;"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by BIGINT;"))
        await conn.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS duration_days INTEGER;"))
        await conn.execute(text("ALTER TABLE deliveries ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP;"))
