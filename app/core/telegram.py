from telegram import Bot, Update, Message
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
from telegram.constants import ParseMode
from loguru import logger
from typing import Optional
import asyncio

from env import env
from app.services.cache_service import CacheService
from app.services.price_service import price_service
from app.services.news_service import news_service
from app.services.alert_service import alert_service
from app.services.notification_service import notification_service
from app.core.db import db
from app.services.coin_service import coin_service

# Import handlers
from app.core.handlers.start_handlers import start_command, help_command
from app.core.handlers.price_handlers import price_command, coins_command, price_history_command
from app.core.handlers.news_handlers import news_command, headlines_command
from app.core.handlers.alert_handlers import set_alert_command, list_alerts_command, delete_alert_command
from app.core.handlers.callback_handlers import button_callback

class TelegramBot:
    _instance: Optional['TelegramBot'] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TelegramBot, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self.token = env.TELEGRAM_BOT_TOKEN
            self.application: Optional[Application] = None
            self.bot: Optional[Bot] = None
            self.cache = CacheService()
            self._initialized = True
            self._polling_task: Optional[asyncio.Task] = None
            self._alert_task: Optional[asyncio.Task] = None

    async def initialize(self):
        """Initialize the bot and prepare for polling"""
        try:
            # Initialize services
            await price_service.initialize()
            await news_service.initialize()
            await db.connect()  # Initialize database connection
            
            # Initialize bot and application
            self.bot = Bot(token=self.token)
            self.application = (
                Application.builder()
                .bot(self.bot)
                .build()
            )

            # Set bot in notification service
            notification_service.set_bot(self.bot)

            # Register handlers
            await self._register_handlers()

            # Initialize the application
            await self.application.initialize()
            await self.application.start()
            
            # Start polling in a background task
            self._polling_task = asyncio.create_task(self._start_polling())
            
            # Start alert checker in background
            self._alert_task = asyncio.create_task(self._check_alerts_loop())
            
            logger.info("Telegram bot initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Telegram bot: {e}")
            raise

    async def _start_polling(self):
        """Run polling in an infinite loop"""
        try:
            logger.info("Starting bot polling...")
            await self.application.updater.start_polling()
        except Exception as e:
            logger.error(f"Polling error: {e}")
            raise

    async def _send_loading_message(self, update: Update) -> Optional[Message]:
        """Send a loading message and return it for later deletion"""
        try:
            # Use update.message if available, otherwise assume it's a callback_query and use update.callback_query.message
            if update.message:
                return await update.message.reply_text("⏳ Processing your request...")
            elif update.callback_query and update.callback_query.message:
                return await update.callback_query.message.reply_text("⏳ Processing your request...")
            return None
        except Exception as e:
            logger.error(f"Error sending loading message: {e}")
            return None

    async def _delete_message_safe(self, message: Optional[Message]):
        """Safely delete a message"""
        if message:
            try:
                await message.delete()
            except Exception as e:
                logger.error(f"Error deleting message: {e}")

    async def _register_handlers(self):
        """Register command handlers"""
        if not self.application:
            raise RuntimeError("Application not initialized")

        commands = [
            ("start", "Start the bot", lambda u, c: start_command(u, c)),
            ("help", "Show available commands", lambda u, c: help_command(u, c)),
            ("price", "Get current price for a coin", lambda u, c: price_command(u, c, price_service)),
            ("coins", "List supported coins", lambda u, c: coins_command(u, c, coin_service)),
            ("history", "View price history", lambda u, c: price_history_command(u, c, price_service)),
            ("headlines", "Get top 5 crypto headlines", lambda u, c: headlines_command(u, c, news_service)),
            ("news", "Get latest crypto news with images and descriptions", lambda u, c: news_command(u, c, news_service)),
            ("setalert", "Set price alert", lambda u, c: set_alert_command(u, c, alert_service, price_service)),
            ("alerts", "View your active alerts", lambda u, c: list_alerts_command(u, c, alert_service, price_service)),
            ("delalert", "Delete an alert", lambda u, c: delete_alert_command(u, c, alert_service)),
        ]

        # Register command handlers
        for command, _, handler in commands:
            self.application.add_handler(CommandHandler(command, handler))
        
        # Register callback query handler
        self.application.add_handler(CallbackQueryHandler(lambda u, c: button_callback(u, c, price_service, coin_service)))

        # Set commands in Telegram
        await self.bot.set_my_commands([
            (command, description) for command, description, _ in commands
        ])

        logger.info("Command handlers registered")

    async def _check_alerts_loop(self):
        """Periodically check alerts in background with improved notification formatting"""
        while True:
            try:
                triggered_alerts = await alert_service.check_alerts()
                
                # Process notifications in parallel
                tasks = []
                for alert in triggered_alerts:
                    symbol = alert['symbol'].upper()
                    target_price = alert['target_price']
                    current_price = alert['current_price']
                    price_diff = ((current_price - target_price) / target_price * 100)
                    condition = alert['condition']
                    
                    # Get additional price data if available
                    price_data_info = alert.get('price_data', {})
                    high_24h = price_data_info.get('high_24h', 0)
                    low_24h = price_data_info.get('low_24h', 0)
                    change_24h = price_data_info.get('change_24h', 0)
                    
                    # Determine direction emoji and status
                    direction_emoji = '📈' if condition == 'above' else '📉'
                    
                    # Format the alert message with markdown
                    message = (
                        f"{direction_emoji} *PRICE ALERT* {direction_emoji}\n\n"
                        f"• *{symbol}* is now *{condition.upper()}* your target price!\n\n"
                        f"🎯 *Target:* ${target_price:,.2f} ({condition})\n"
                        f"💰 *Current:* ${current_price:,.2f} ({price_diff:+.2f}%)"
                    )
                    
                    # Add 24h stats if available
                    if high_24h or low_24h:
                        message += (
                            f"\n\n📊 *24h Stats:*\n"
                            f"• High: ${high_24h:,.2f}\n"
                            f"• Low: ${low_24h:,.2f}\n"
                            f"• Change: {change_24h:+.2f}%"
                        )
                    
                    # Add action buttons
                    message += "\n\n🔔 Use /alerts to manage your alerts"
                    
                    # Send the notification
                    tasks.append(
                        notification_service.send_message(
                            chat_id=alert['user_id'],
                            text=message,
                            parse_mode=ParseMode.MARKDOWN
                        )
                    )
                
                # Send all notifications in parallel
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                
                # Wait for 1 minute before next check
                await asyncio.sleep(60)
            
            except Exception as e:
                logger.error(f"Error in alert checker loop: {e}")
                await asyncio.sleep(60)  # Wait before retrying

    async def shutdown(self):
        """Shutdown the bot and clean up resources"""
        try:
            if self._polling_task:
                self._polling_task.cancel()
                try:
                    await self._polling_task
                except asyncio.CancelledError:
                    pass

            if self._alert_task:
                self._alert_task.cancel()
                try:
                    await self._alert_task
                except asyncio.CancelledError:
                    pass

            if self.application:
                await self.application.stop()
                await self.application.shutdown()
            
            # Cleanup services
            await price_service.close()
            await news_service.close()
            await db.disconnect()  # Close database connection
            await self.cache.close()
            
            logger.info("Telegram bot shut down successfully")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
            raise

# Create singleton instance
bot_instance = TelegramBot()