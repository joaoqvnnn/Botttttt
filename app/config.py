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

    # Módulo 03 — link de ativação (aceita {order_id} para substituição)
    ACTIVATION_URL: str = ""

    @property
    def async_database_url(self) -> str:
        url = self.DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url


settings = Settings()
