from typing import Optional
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
            self.bot = None
            self._initialized = True

    def set_bot(self, bot):
        """Set the bot instance for sending notifications"""
        self.bot = bot

    async def send_message(self, chat_id: int, message: str):
        """Send a message to a specific chat"""
        try:
            if self.bot:
                await self.bot.send_message(chat_id=chat_id, text=message)
            else:
                logger.warning("Bot not initialized for notifications")
        except Exception as e:
            logger.error(f"Error sending notification: {e}")

# Create singleton instance
notification_service = NotificationService() 