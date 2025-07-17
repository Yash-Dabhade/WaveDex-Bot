from typing import Optional, Any
from loguru import logger

class NotificationService:
    _instance: Optional['NotificationService'] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(NotificationService, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._bot = None
            self._initialized = True

    def set_bot(self, bot: Any):
        """Set the bot instance for sending messages"""
        self._bot = bot

    async def send_message(self, chat_id: int, text: str) -> bool:
        """Send a message to a specific chat"""
        try:
            if not self._bot:
                logger.warning("Bot not initialized in notification service")
                return False

            await self._bot.send_message(
                chat_id=chat_id,
                text=text
            )
            return True
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
            return False

# Create singleton instance
notification_service = NotificationService() 