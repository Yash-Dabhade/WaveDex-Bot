from pydantic_settings import BaseSettings
from typing import Optional
from functools import lru_cache

class Settings(BaseSettings):
    # App Settings
    APP_ENV: str = "development"
    APP_DEBUG: bool = True
    APP_SECRET_KEY: str
    LOG_LEVEL: str = "INFO"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Database
    DATABASE_URL: str

    # Telegram
    TELEGRAM_BOT_TOKEN: str

    # API Keys
    COINGECKO_API_KEY: str = ""
    CRYPTOPANIC_API_KEY: str
    NEWS_API_KEY: Optional[str] = None
    COINMARKETCAP_API_KEY: str = None

    class Config:
        env_file = ".env"
        case_sensitive = True

@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings() 