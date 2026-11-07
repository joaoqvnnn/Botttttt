from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    BOT_TOKEN: str

    CHANNEL_ID: str
    CHANNEL_LINK: str
    GROUP_ID: str
    GROUP_LINK: str

    WEBHOOK_URL: str = ""
    USE_WEBHOOK: bool = True

    DATABASE_URL: str

    # Catálogo
    PRODUCTS_PER_PAGE: int = 5
    SUBSCRIPTIONS_PER_PAGE: int = 6

    # Ativação
    ACTIVATION_URL: str = ""

    # ─── Módulo 06 — PIX / Mercado Pago ───────────────
    MP_ACCESS_TOKEN: str = ""
    PIX_MIN_DEPOSIT: float = 5.00
    PIX_BONUS_PERCENT: float = 0.0
    PIX_EXPIRATION_MINUTES: int = 30
    MP_WEBHOOK_SECRET: str = ""

    @property
    def async_database_url(self) -> str:
        url = self.DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url


settings = Settings()
