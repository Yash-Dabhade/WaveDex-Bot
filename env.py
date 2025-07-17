import os
from pathlib import Path
from dotenv import load_dotenv
from typing import Optional, Any, Dict

# Load environment variables from .env file
load_dotenv()

class Environment:
    def __init__(self):
        # App Settings
        self.APP_ENV = os.getenv("APP_ENV", "development")
        self.APP_DEBUG = os.getenv("APP_DEBUG", "true").lower() in ("true", "1", "t")
        self.APP_SECRET_KEY = os.getenv("APP_SECRET_KEY", "")
        self.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

        # Server
        self.HOST = os.getenv("HOST", "0.0.0.0")
        self.PORT = int(os.getenv("PORT", "8000"))

        # Database
        self.DATABASE_URL = os.getenv("DATABASE_URL", "")

        # Telegram
        self.TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

        # API Keys
        self.COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "")
        self.CRYPTOPANIC_API_KEY = os.getenv("CRYPTOPANIC_API_KEY", "")
        self.NEWS_API_KEY = os.getenv("NEWS_API_KEY")
        self.COINDESK_API_KEY = os.getenv("COINDESK_API_KEY")

        # Validate required settings
        if not self.APP_SECRET_KEY:
            raise ValueError("APP_SECRET_KEY must be set in .env file")

        if not self.DATABASE_URL:
            raise ValueError("DATABASE_URL must be set in .env file")

        if not self.TELEGRAM_BOT_TOKEN:
            raise ValueError("TELEGRAM_BOT_TOKEN must be set in .env file")

    def __getattr__(self, name: str) -> Any:
        """Allow accessing attributes with dot notation"""
        try:
            return self.__dict__[name]
        except KeyError:
            raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

# Create a single instance of the environment
env = Environment()
