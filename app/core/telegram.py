from telegram import Bot, Update, Message
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode
from loguru import logger
from typing import Optional, Tuple
import asyncio
from datetime import datetime, timedelta

from app.core.config import settings
from app.services.cache_service import CacheService
from app.services.price_service import price_service
from app.services.news_service import news_service
from app.services.alert_service import alert_service
from app.services.notification_service import notification_service
from app.services.portfolio_service import portfolio_service
from app.services.prisma_service import prisma_service

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
            await prisma_service.initialize()  # Initialize Prisma service
            
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
            return await update.message.reply_text("⏳ Processing your request...")
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
            ("start", "Start the bot", self._start_command),
            ("help", "Show available commands", self._help_command),
            ("price", "Get current price for a coin", self._price_command),
            ("coins", "List supported coins", self._coins_command),
            ("history", "View price history", self._price_history_command),
            ("alert", "Set price alert", self._set_alert_command),
            ("alerts", "View your active alerts", self._list_alerts_command),
            ("delalert", "Delete an alert", self._delete_alert_command),
            ("news", "Get latest crypto news", self._news_command),
            ("portfolio", "View your portfolio", self._portfolio_command),
            ("trending", "Show trending coins", self._trending_command),
            ("add", "Add position to portfolio", self._add_position_command),
            ("remove", "Remove position from portfolio", self._remove_position_command),
        ]

        # Register handlers
        for command, description, handler in commands:
            self.application.add_handler(CommandHandler(command, handler))

        # Set commands in Telegram
        await self.bot.set_my_commands([
            (command, description) for command, description, _ in commands
        ])

        logger.info("Command handlers registered")

    async def _start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        welcome_message = (
            "👋 Welcome to CryptoTracker!\n\n"
            "I can help you track crypto prices, manage your portfolio, "
            "and stay updated with market movements.\n\n"
            "Use /help to see available commands."
        )
        await update.message.reply_text(welcome_message)

    async def _help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        help_message = (
            "📱 Available Commands:\n\n"
            "💰 Prices & Market\n"
            "/price [symbol] - Current price & stats\n"
            "/coins - List supported coins\n"
            "/history [symbol] [days] - Price history\n"
            "/trending - Top movers\n\n"
            "📈 Portfolio\n"
            "/portfolio - View your portfolio\n"
            "/add [symbol] [quantity] [price] - Add position\n"
            "/remove [symbol] [quantity] - Remove position\n\n"
            "⚡️ Alerts\n"
            "/alert [symbol] [price] [above/below] - Set alert\n"
            "/alerts - View your alerts\n"
            "/delalert [id] - Delete alert\n\n"
            "📰 News\n"
            "/news [symbol] - Latest crypto news"
        )
        await update.message.reply_text(help_message)

    async def _price_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /price command"""
        try:
            if not context.args:
                await update.message.reply_text(
                    "Please provide a cryptocurrency symbol.\n"
                    "Example: /price btc\n"
                    "Use /coins to see supported cryptocurrencies"
                )
                return

            # Show loading message
            loading_msg = await self._send_loading_message(update)

            symbol = context.args[0].lower()
            price_data = await price_service.get_price(symbol)

            # Delete loading message
            await self._delete_message_safe(loading_msg)

            if "error" in price_data:
                await update.message.reply_text(f"❌ {price_data['error']}")
                return

            # Format the price message with more details
            message = (
                f"💰 {price_data['symbol']} Price Analysis:\n\n"
                f"Current Price: ${price_data['price_usd']:,.2f}\n"
                f"24h Change: {price_data['change_24h']:+.2f}%\n"
                f"24h Volume: ${price_data['volume_24h']:,.0f}\n"
                f"Market Cap: ${price_data['market_cap']:,.0f}\n\n"
                f"Quick Actions:\n"
                f"📈 Price History: /history {symbol}\n"
                f"🔔 Set Alert: /alert {symbol} [price] [above/below]\n"
                f"📰 Latest News: /news {symbol}"
            )

            await update.message.reply_text(message)

        except Exception as e:
            logger.error(f"Error in price command: {e}")
            await self._delete_message_safe(loading_msg)
            await update.message.reply_text("❌ Failed to fetch price data. Please try again later.")

    async def _coins_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /coins command"""
        try:
            loading_msg = await self._send_loading_message(update)
            
            coins = await price_service.get_supported_coins()
            
            await self._delete_message_safe(loading_msg)

            if "error" in coins:
                await update.message.reply_text(f"❌ {coins['error']}")
                return

            # Split coins into multiple messages if needed
            message = "🪙 Supported Cryptocurrencies:\n\n"
            chunks = []
            current_chunk = []

            for coin in coins['coins']:
                line = f"• {coin['symbol'].upper()}: {coin['name']}\n"
                if len(message) + len("".join(current_chunk)) + len(line) > 4000:
                    chunks.append("".join(current_chunk))
                    current_chunk = []
                current_chunk.append(line)

            if current_chunk:
                chunks.append("".join(current_chunk))

            # Send messages
            await update.message.reply_text(message)
            for chunk in chunks:
                await update.message.reply_text(chunk)

        except Exception as e:
            logger.error(f"Error in coins command: {e}")
            await self._delete_message_safe(loading_msg)
            await update.message.reply_text("❌ Failed to fetch supported coins. Please try again later.")

    async def _price_history_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /history command"""
        try:
            if not context.args:
                await update.message.reply_text(
                    "Please provide a cryptocurrency symbol and optional number of days.\n"
                    "Example: /history btc 7"
                )
                return

            loading_msg = await self._send_loading_message(update)

            symbol = context.args[0].lower()
            days = int(context.args[1]) if len(context.args) > 1 else 7
            
            # Limit days to reasonable range
            days = min(max(days, 1), 30)

            history = await price_service.get_price_history(symbol, days)
            
            await self._delete_message_safe(loading_msg)

            if "error" in history:
                await update.message.reply_text(f"❌ {history['error']}")
                return

            # Format price history message
            message = f"📊 {history['symbol']} Price History ({days} days):\n\n"
            
            for entry in history['history']:
                date = datetime.fromtimestamp(entry['timestamp']).strftime('%Y-%m-%d')
                message += (
                    f"📅 {date}\n"
                    f"Price: ${entry['price']:,.2f}\n"
                    f"Change: {entry['change_24h']:+.2f}%\n"
                    f"Volume: ${entry['volume']:,.0f}\n"
                    f"---------------\n"
                )

            await update.message.reply_text(message)

        except ValueError:
            await self._delete_message_safe(loading_msg)
            await update.message.reply_text("❌ Invalid number of days. Please provide a number between 1 and 30.")
        except Exception as e:
            logger.error(f"Error in history command: {e}")
            await self._delete_message_safe(loading_msg)
            await update.message.reply_text("❌ Failed to fetch price history. Please try again later.")

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

    async def _set_alert_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /alert command"""
        try:
            if not context.args or len(context.args) < 3:
                await update.message.reply_text(
                    "Please provide symbol, price, and condition (above/below).\n"
                    "Example: /alert btc 50000 above"
                )
                return

            loading_msg = await self._send_loading_message(update)

            symbol = context.args[0].lower()
            try:
                price = float(context.args[1])
                condition = context.args[2].lower()
            except ValueError:
                await self._delete_message_safe(loading_msg)
                await update.message.reply_text("❌ Invalid price value")
                return

            result = await alert_service.set_alert(
                user_id=update.effective_user.id,
                symbol=symbol,
                target_price=price,
                condition=condition
            )

            await self._delete_message_safe(loading_msg)

            if "error" in result:
                await update.message.reply_text(f"❌ {result['error']}")
            else:
                await update.message.reply_text(result["message"])

        except Exception as e:
            logger.error(f"Error in alert command: {e}")
            await self._delete_message_safe(loading_msg)
            await update.message.reply_text("❌ Failed to set alert. Please try again later.")

    async def _list_alerts_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /alerts command"""
        try:
            loading_msg = await self._send_loading_message(update)

            alerts = await alert_service.get_user_alerts(update.effective_user.id)
            
            await self._delete_message_safe(loading_msg)

            if not alerts:
                await update.message.reply_text("You don't have any active alerts.")
                return

            message = "🔔 Your Active Alerts:\n\n"
            for alert in alerts:
                # Calculate price difference
                diff = ((alert["current_price"] - alert["target_price"]) / alert["target_price"]) * 100
                
                message += (
                    f"ID: {alert['id']}\n"
                    f"Symbol: {alert['symbol']}\n"
                    f"Target: ${alert['target_price']:,.2f} ({alert['condition']})\n"
                    f"Current: ${alert['current_price']:,.2f} ({diff:+.2f}%)\n"
                    f"Created: {datetime.fromtimestamp(alert['created_at']).strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"---------------\n"
                )

            await update.message.reply_text(message)

        except Exception as e:
            logger.error(f"Error in alerts command: {e}")
            await self._delete_message_safe(loading_msg)
            await update.message.reply_text("❌ Failed to fetch alerts. Please try again later.")

    async def _delete_alert_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /delalert command"""
        try:
            if not context.args:
                await update.message.reply_text(
                    "Please provide the alert ID.\n"
                    "Use /alerts to see your active alerts and their IDs"
                )
                return

            loading_msg = await self._send_loading_message(update)

            alert_id = context.args[0]
            result = await alert_service.delete_alert(
                user_id=update.effective_user.id,
                alert_id=alert_id
            )

            await self._delete_message_safe(loading_msg)

            if "error" in result:
                await update.message.reply_text(f"❌ {result['error']}")
            else:
                await update.message.reply_text(result["message"])

        except Exception as e:
            logger.error(f"Error in delalert command: {e}")
            await self._delete_message_safe(loading_msg)
            await update.message.reply_text("❌ Failed to delete alert. Please try again later.")

    async def _check_alerts_loop(self):
        """Periodically check alerts in background"""
        while True:
            try:
                triggered_alerts = await alert_service.check_alerts()
                
                # Send notifications for triggered alerts
                for alert in triggered_alerts:
                    message = (
                        f"🚨 Price Alert for {alert['symbol']}!\n\n"
                        f"Target: ${alert['target_price']:,.2f} ({alert['condition']})\n"
                        f"Current Price: ${alert['current_price']:,.2f}\n"
                        f"24h Change: {alert['price_data']['change_24h']:+.2f}%\n\n"
                        f"Use /alerts to manage your alerts"
                    )
                    
                    await notification_service.send_message(
                        chat_id=alert['user_id'],
                        text=message
                    )
                
                # Wait for 1 minute before next check
                await asyncio.sleep(60)
            
            except Exception as e:
                logger.error(f"Error in alert checker loop: {e}")
                await asyncio.sleep(60)  # Wait before retrying

    async def _portfolio_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /portfolio command"""
        try:
            # Show loading message
            loading_msg = await self._send_loading_message(update)

            # Get user's watchlist performance
            performance = await portfolio_service.get_watchlist_performance(str(update.effective_user.id))

            # Delete loading message
            await self._delete_message_safe(loading_msg)

            if not performance:
                await update.message.reply_text(
                    "📈 Your Portfolio is Empty\n\n"
                    "Start building your portfolio:\n"
                    "➕ /add [symbol] [quantity] [price]\n"
                    "Example: /add btc 0.1 45000\n\n"
                    "🔍 Find opportunities:\n"
                    "• /price [symbol] - Check current prices\n"
                    "• /trending - View trending coins\n"
                    "• /news - Latest market news"
                )
                return

            # Format the performance message
            message = "💼 Your Portfolio Performance 📊\n\n"
            
            total_value = 0
            total_change_24h = 0
            
            for coin in performance:
                price_change = coin["price_change_24h"]
                change_emoji = "🟢" if price_change >= 0 else "🔴"
                position_value = coin["price"] * coin.get("quantity", 0)
                total_value += position_value
                total_change_24h += position_value * (price_change / 100)
                
                message += (
                    f"{change_emoji} {coin['symbol']}\n"
                    f"├ Price: ${coin['price']:,.2f}\n"
                    f"├ 24h Change: {price_change:+.2f}%\n"
                    f"├ Value: ${position_value:,.2f}\n"
                    f"└ Volume: ${coin['volume_24h']:,.0f}\n\n"
                )

            # Add portfolio summary
            total_change_percent = (total_change_24h / total_value * 100) if total_value > 0 else 0
            summary_emoji = "📈" if total_change_percent >= 0 else "📉"
            
            message += (
                f"📊 Portfolio Summary {summary_emoji}\n"
                f"├ Total Value: ${total_value:,.2f}\n"
                f"└ 24h Change: {total_change_percent:+.2f}% (${total_change_24h:,.2f})\n\n"
                f"Quick Actions:\n"
                f"➕ /add - Add position\n"
                f"➖ /remove - Remove position\n"
                f"🔔 /alert - Set price alert"
            )

            await update.message.reply_text(message)

        except Exception as e:
            logger.error(f"Error in portfolio command: {e}")
            await self._delete_message_safe(loading_msg)
            await update.message.reply_text("❌ Failed to fetch portfolio data. Please try again later.")

    async def _trending_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /trending command"""
        try:
            # Show loading message
            loading_msg = await self._send_loading_message(update)

            # Get trending coins
            trending = await portfolio_service.get_trending_coins(limit=10)

            # Delete loading message
            await self._delete_message_safe(loading_msg)

            if not trending:
                await update.message.reply_text(
                    "❌ No trending data available right now.\n\n"
                    "Try these instead:\n"
                    "📊 /price btc - Check Bitcoin price\n"
                    "📰 /news - Get latest crypto news\n"
                    "💼 /portfolio - View your portfolio"
                )
                return

            # Format the trending message
            message = "🔥 Top Movers in 24h 🔥\n\n"
            
            # Split into gainers and losers
            gainers = [c for c in trending if c["percent_change_24h"] > 0]
            losers = [c for c in trending if c["percent_change_24h"] <= 0]
            
            # Format price based on value
            def format_price(price: float) -> str:
                if price < 0.01:
                    return f"${price:.8f}"
                elif price < 1:
                    return f"${price:.4f}"
                else:
                    return f"${price:,.2f}"

            # Show top gainers
            if gainers:
                message += "📈 TOP GAINERS\n"
                for i, coin in enumerate(gainers[:5], 1):
                    rank_emoji = "👑" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🏅"
                    message += (
                        f"{rank_emoji} {coin['symbol']} ({coin['name']})\n"
                        f"├ Price: {format_price(coin['price'])}\n"
                        f"├ 24h: +{coin['percent_change_24h']:.1f}%\n"
                        f"├ 1h: {coin['percent_change_1h']:+.1f}%\n"
                        f"└ Vol: ${coin['volume_24h']:,.0f}\n\n"
                    )

            # Show top losers
            if losers:
                message += "📉 TOP LOSERS\n"
                for i, coin in enumerate(losers[:5], 1):
                    rank_emoji = "💔" if i == 1 else "💢" if i == 2 else "⚠️" if i == 3 else "📌"
                    message += (
                        f"{rank_emoji} {coin['symbol']} ({coin['name']})\n"
                        f"├ Price: {format_price(coin['price'])}\n"
                        f"├ 24h: {coin['percent_change_24h']:.1f}%\n"
                        f"├ 1h: {coin['percent_change_1h']:+.1f}%\n"
                        f"└ Vol: ${coin['volume_24h']:,.0f}\n\n"
                    )

            message += (
                "💡 Quick Actions:\n"
                "• /price [symbol] - Get detailed price info\n"
                "• /add [symbol] [quantity] [price] - Add to portfolio\n"
                "• /alert [symbol] [price] [above/below] - Set alert\n\n"
                "ℹ️ Data updates every 10 minutes"
            )

            await update.message.reply_text(message)

        except Exception as e:
            logger.error(f"Error in trending command: {e}")
            await self._delete_message_safe(loading_msg)
            await update.message.reply_text(
                "❌ Failed to fetch trending data.\n\n"
                "This might be due to API rate limits. Please try again in a minute."
            )

    async def _add_position_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /add command"""
        try:
            if not context.args or len(context.args) < 3:
                await update.message.reply_text(
                    "ℹ️ Add Position Guide:\n\n"
                    "Format: /add [symbol] [quantity] [price]\n"
                    "Example: /add btc 0.5 45000\n\n"
                    "💡 Tips:\n"
                    "• Use lowercase symbols (btc, eth, etc.)\n"
                    "• Quantity can be decimal (0.5, 1.23, etc.)\n"
                    "• Price in USD without $ symbol\n\n"
                    "🔍 Need help?\n"
                    "• /price [symbol] - Check current prices\n"
                    "• /coins - List supported coins"
                )
                return

            # Show loading message
            loading_msg = await self._send_loading_message(update)

            try:
                symbol = context.args[0].lower()
                quantity = float(context.args[1])
                price = float(context.args[2])
            except ValueError:
                await self._delete_message_safe(loading_msg)
                await update.message.reply_text("❌ Invalid quantity or price value")
                return

            # Add position
            result = await portfolio_service.add_position(
                user_id=str(update.effective_user.id),
                symbol=symbol,
                quantity=quantity,
                price=price
            )

            await self._delete_message_safe(loading_msg)

            # Get current price for comparison
            price_data = await price_service.get_price(symbol)
            current_price = price_data["price_usd"] if "error" not in price_data else price

            # Calculate position value
            position_value = quantity * current_price
            cost_basis = quantity * price
            unrealized_pnl = position_value - cost_basis
            pnl_percentage = ((current_price - price) / price) * 100 if price > 0 else 0

            # Choose emoji based on P&L
            pnl_emoji = "📈" if pnl_percentage >= 0 else "📉"
            
            message = (
                f"✅ Position Added Successfully!\n\n"
                f"💎 {symbol.upper()} Position Details:\n"
                f"├ Quantity: {quantity:,.8f}\n"
                f"├ Avg Price: ${price:,.2f}\n"
                f"├ Current: ${current_price:,.2f}\n"
                f"├ Value: ${position_value:,.2f}\n"
                f"└ P&L: {pnl_emoji} ${unrealized_pnl:,.2f} ({pnl_percentage:+.2f}%)\n\n"
                f"Quick Actions:\n"
                f"📊 /portfolio - View full portfolio\n"
                f"🔔 /alert - Set price alert\n"
                f"📰 /news {symbol} - Get latest news"
            )

            await update.message.reply_text(message)

        except ValueError as e:
            await self._delete_message_safe(loading_msg)
            await update.message.reply_text(f"❌ {str(e)}")
        except Exception as e:
            logger.error(f"Error in add command: {e}")
            await self._delete_message_safe(loading_msg)
            await update.message.reply_text("❌ Failed to add position. Please try again later.")

    async def _remove_position_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /remove command"""
        try:
            if not context.args or len(context.args) < 2:
                await update.message.reply_text(
                    "ℹ️ Remove Position Guide:\n\n"
                    "Format: /remove [symbol] [quantity]\n"
                    "Example: /remove btc 0.1\n\n"
                    "💡 Tips:\n"
                    "• Use lowercase symbols (btc, eth, etc.)\n"
                    "• Quantity must be less than or equal to your holdings\n"
                    "• View your holdings with /portfolio\n\n"
                    "❓ Need help?\n"
                    "• /portfolio - Check your positions\n"
                    "• /price [symbol] - Get current prices"
                )
                return

            # Show loading message
            loading_msg = await self._send_loading_message(update)

            try:
                symbol = context.args[0].lower()
                quantity = float(context.args[1])
            except ValueError:
                await self._delete_message_safe(loading_msg)
                await update.message.reply_text("❌ Invalid quantity value")
                return

            # Remove position
            result = await portfolio_service.remove_position(
                user_id=str(update.effective_user.id),
                symbol=symbol,
                quantity=quantity
            )

            await self._delete_message_safe(loading_msg)

            if result is None:
                message = (
                    f"✅ Position Fully Closed\n\n"
                    f"Successfully removed all {symbol.upper()} from your portfolio\n\n"
                    f"Quick Actions:\n"
                    f"📊 /portfolio - View remaining positions\n"
                    f"➕ /add - Add new position\n"
                    f"🔥 /trending - Discover opportunities"
                )
            else:
                # Get current price
                price_data = await price_service.get_price(symbol)
                current_price = price_data["price_usd"] if "error" not in price_data else 0

                # Calculate remaining position
                remaining_quantity = result.quantity
                position_value = remaining_quantity * current_price

                message = (
                    f"✅ Position Partially Closed\n\n"
                    f"💫 {symbol.upper()} Update:\n"
                    f"├ Removed: {quantity:,.8f}\n"
                    f"├ Remaining: {remaining_quantity:,.8f}\n"
                    f"└ Current Value: ${position_value:,.2f}\n\n"
                    f"Quick Actions:\n"
                    f"📊 /portfolio - View full portfolio\n"
                    f"🔔 /alert - Set price alert\n"
                    f"📈 /price {symbol} - Check price"
                )

            await update.message.reply_text(message)

        except ValueError as e:
            await self._delete_message_safe(loading_msg)
            await update.message.reply_text(f"❌ {str(e)}")
        except Exception as e:
            logger.error(f"Error in remove command: {e}")
            await self._delete_message_safe(loading_msg)
            await update.message.reply_text("❌ Failed to remove position. Please try again later.")

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
            await prisma_service.shutdown()  # Shutdown Prisma service
            await self.cache.close()
            
            logger.info("Telegram bot shut down successfully")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
            raise

# Create singleton instance
bot_instance = TelegramBot() 