from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes
from loguru import logger
from typing import Optional
import asyncio

from app.core.config import settings
from app.services.redis_service import RedisService
from app.services.price_service import price_service
from app.services.news_service import news_service

class TelegramBot:
    _instance: Optional['TelegramBot'] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TelegramBot, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self.token = settings.TELEGRAM_BOT_TOKEN
            self.application: Optional[Application] = None
            self.bot: Optional[Bot] = None
            self.redis = RedisService()
            self._initialized = True
            self._polling_task: Optional[asyncio.Task] = None

    async def initialize(self):
        """Initialize the bot and prepare for polling"""
        try:
            # Initialize services
            await price_service.initialize()
            await news_service.initialize()
            
            # Initialize bot and application
            self.bot = Bot(token=self.token)
            self.application = (
                Application.builder()
                .bot(self.bot)
                .build()
            )

            # Register handlers
            await self._register_handlers()

            # Initialize the application
            await self.application.initialize()
            await self.application.start()
            
            # Start polling in a background task
            self._polling_task = asyncio.create_task(self._start_polling())
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

    async def _register_handlers(self):
        """Register command handlers"""
        if not self.application:
            raise RuntimeError("Application not initialized")

        # Basic commands
        self.application.add_handler(CommandHandler("start", self._start_command))
        self.application.add_handler(CommandHandler("help", self._help_command))
        
        # Price commands
        self.application.add_handler(CommandHandler("price", self._price_command))
        
        # News commands
        self.application.add_handler(CommandHandler("news", self._news_command))

        logger.info("Command handlers registered")

    async def _start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        welcome_message = (
            "🚀 Welcome to Crypto News Bot!\n\n"
            "I'm here to help you track crypto prices and news.\n\n"
            "Available commands:\n"
            "/price [symbol] - Get current price\n"
            "/news [symbol] - Get latest news (optional: specify symbol)\n"
            "/help - Show all commands"
        )
        await update.message.reply_text(welcome_message)

    async def _help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        help_message = (
            "📚 Available Commands:\n\n"
            "Price Tracking:\n"
            "/price [symbol] - Current price and stats\n"
            "Example: /price btc\n\n"
            "News:\n"
            "/news - Get latest crypto news\n"
            "/news [symbol] - Get news for specific coin\n"
            "Example: /news eth"
        )
        await update.message.reply_text(help_message)

    async def _price_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /price command"""
        try:
            if not context.args:
                await update.message.reply_text(
                    "Please provide a cryptocurrency symbol.\n"
                    "Example: /price btc"
                )
                return

            symbol = context.args[0].lower()
            price_data = await price_service.get_price(symbol)

            if "error" in price_data:
                await update.message.reply_text(f"❌ {price_data['error']}")
                return

            # Format the price message
            message = (
                f"💰 {price_data['symbol']} Price:\n\n"
                f"Current Price: ${price_data['price_usd']:,.2f}\n"
                f"24h Change: {price_data['change_24h']:+.2f}%\n"
                f"24h Volume: ${price_data['volume_24h']:,.0f}\n"
                f"Market Cap: ${price_data['market_cap']:,.0f}"
            )

            await update.message.reply_text(message)

        except Exception as e:
            logger.error(f"Error in price command: {e}")
            await update.message.reply_text("❌ Failed to fetch price data. Please try again later.")

    async def _news_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /news command"""
        try:
            # Get symbol if provided
            symbol = context.args[0].lower() if context.args else None
            
            # Fetch news (limit to 3 items to avoid message length issues)
            news_data = await news_service.get_news(symbol, limit=3)
            
            if "error" in news_data:
                await update.message.reply_text(f"❌ {news_data['error']}")
                return

            # Send header message
            header = f"📰 Latest News for {news_data['symbol']}:"
            await update.message.reply_text(header)
            
            # Send each news item as a separate message
            for item in news_data['news']:
                # Escape special characters in title
                title = item['title'].replace('[', '\\[').replace('*', '\\*').replace('_', '\\_').replace('`', '\\`')
                
                message = (
                    f"🔸 {title}\n\n"
                    f"📍 {item['source']} • {item['published']}\n"
                    f"🔗 {item['url']}"
                )
                await update.message.reply_text(
                    message,
                    disable_web_page_preview=True
                )

        except Exception as e:
            logger.error(f"Error in news command: {e}")
            await update.message.reply_text("❌ Failed to fetch news. Please try again later.")

    async def shutdown(self):
        """Shutdown the bot and clean up resources"""
        try:
            if self._polling_task:
                self._polling_task.cancel()
                try:
                    await self._polling_task
                except asyncio.CancelledError:
                    pass

            if self.application:
                await self.application.stop()
                await self.application.shutdown()
            
            # Cleanup services
            await price_service.close()
            await news_service.close()
            await self.redis.close()
            
            logger.info("Telegram bot shut down successfully")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
            raise

# Create singleton instance
bot_instance = TelegramBot() 