import sys
from loguru import logger
from app.core.config import settings

def setup_logging():
    # Remove default handler
    logger.remove()

    # Add console handler with custom format
    logger.add(
        sys.stderr,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
        level=settings.LOG_LEVEL,
        backtrace=True,
        diagnose=True,
    )

    # Add file handler for errors
    logger.add(
        "logs/error.log",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
        level="ERROR",
        rotation="1 day",
        retention="7 days",
        backtrace=True,
        diagnose=True,
    )

    # Add file handler for all logs
    logger.add(
        "logs/app.log",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
        level=settings.LOG_LEVEL,
        rotation="1 day",
        retention="7 days",
    )

    logger.info(f"Logging setup complete. Level: {settings.LOG_LEVEL}") 