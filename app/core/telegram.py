from telegram import Bot, Update, Message, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from telegram.constants import ParseMode
from loguru import logger
from typing import Optional, Tuple
import asyncio
from datetime import datetime, timedelta

from env import env
from app.services.cache_service import CacheService
from app.services.price_service import price_service
from app.services.news_service import news_service
from app.services.alert_service import alert_service
from app.services.notification_service import notification_service
from app.services.portfolio_service import portfolio_service
from app.core.db import db
from app.services.coin_service import coin_service

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

        # Define command handlers with descriptions
        commands = [
            ("start", "Start the bot", self._start_command),
            ("help", "Show available commands", self._help_command),
            ("price", "Get current price for a coin", self._price_command),
            ("coins", "List supported coins", self._coins_command),
            ("history", "View price history", self._price_history_command),
            ("trending", "Show trending coins", self._trending_command),
            ("headlines", "Get top 5 crypto headlines", self._headlines_command),
            ("news", "Get latest crypto news with images and descriptions", self._news_command),
            ("setalert", "Set price alert", self._set_alert_command),
            ("alerts", "View your active alerts", self._list_alerts_command),
            ("delalert", "Delete an alert", self._delete_alert_command),
            ("portfolio", "View your portfolio", self._portfolio_command),
            ("add", "Add position to portfolio", self._add_position_command),
            ("remove", "Remove position from portfolio", self._remove_position_command),
        ]

        # Register command handlers
        for command, _, handler in commands:
            self.application.add_handler(CommandHandler(command, handler))
        
        # Register callback query handler
        self.application.add_handler(CallbackQueryHandler(self._button_callback))

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
            "/news - Latest crypto news with images and descriptions\n"
            "/headlines - Top 5 crypto headlines"
        )
        await update.message.reply_text(help_message)

    async def _price_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE, symbol: str = None, is_callback: bool = False):
        """Handle /price command with improved formatting"""
        try:
            # Get symbol from callback or command args
            if not symbol:
                if not context.args:
                    await update.message.reply_text(
                        "💱 <b>Price Check</b>\n\n"
                        "Please provide a cryptocurrency symbol.\n"
                        "Example: <code>/price btc</code>\n"
                        "Use /coins to see supported cryptocurrencies",
                        parse_mode='HTML'
                    )
                    return
                symbol = context.args[0].lower()

            # Show loading message
            message = update.callback_query.message if is_callback else update.message
            loading_msg = None
            if not is_callback:
                loading_msg = await self._send_loading_message(update)

            # Get price data
            price_data = await price_service.get_price(symbol)
            await self._delete_message_safe(loading_msg)

            if not price_data or 'error' in price_data:
                error_msg = (
                    f"❌ <b>Symbol Not Found</b>\n\n"
                    f"Could not find data for <code>{symbol.upper()}</code>.\n"
                    f"Error: {price_data.get('error', 'Unknown error')}\n\n"
                    "Please check the symbol and try again.\n"
                    "Use /coins to see supported cryptocurrencies"
                )
                if is_callback:
                    await update.callback_query.edit_message_text(
                        text=error_msg,
                        parse_mode='HTML',
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔄 Try Again", callback_data=f"price_{symbol}")],
                            [InlineKeyboardButton("❌ Close", callback_data="close")]
                        ])
                    )
                else:
                    await update.message.reply_text(
                        error_msg,
                        parse_mode='HTML',
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔄 Try Again", callback_data=f"price_{symbol}")],
                            [InlineKeyboardButton("❌ Close", callback_data="close")]
                        ])
                    )
                return

            # Format the message with the available data
            change_24h = price_data.get('change_24h', 0)
            change_emoji = '🟢' if change_24h >= 0 else '🔴'
            
            message_text = (
                f"📊 <b>{(symbol or '').upper()} Price</b>\n"
                f"<code>────────────────────</code>\n"
                f"💰 <b>Price:</b> ${price_data.get('price_usd', 0):,.2f}\n"
                f"{change_emoji} <b>24h Change:</b> {change_emoji} {abs(change_24h):.2f}%\n"
                f"📊 <b>24h Volume:</b> ${price_data.get('volume_24h', 0):,.0f}\n"
                f"💎 <b>Market Cap:</b> ${price_data.get('market_cap', 0):,.0f}\n"
                f"<code>────────────────────</code>\n"
                f"🔍 <b>Quick Actions</b> (click buttons below)"
            )

            # Create inline keyboard with actions
            keyboard = [
                [
                    InlineKeyboardButton("📈 View History", callback_data=f"history_{symbol}_7"),
                    InlineKeyboardButton("🔄 Refresh", callback_data=f"price_{symbol}")
                ],
                [
                    InlineKeyboardButton("🔔 Set Price Alert", callback_data=f"alert_{symbol}"),
                    InlineKeyboardButton("📰 Latest News", callback_data=f"news_{symbol}")
                ],
                [
                    InlineKeyboardButton("❌ Close", callback_data="close")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            if is_callback:
                await update.callback_query.edit_message_text(
                    text=message_text,
                    parse_mode='HTML',
                    reply_markup=reply_markup,
                    disable_web_page_preview=True
                )
                await update.callback_query.answer()
            else:
                await update.message.reply_text(
                    message_text,
                    parse_mode='HTML',
                    reply_markup=reply_markup,
                    disable_web_page_preview=True
                )

        except Exception as e:
            logger.error(f"Error in price command: {e}", exc_info=True)
            if 'loading_msg' in locals() and loading_msg:
                try:
                    await self._delete_message_safe(loading_msg)
                except Exception as del_error:
                    logger.error(f"Error deleting loading message: {del_error}")
            
            error_msg = (
                "❌ <b>Error fetching price data</b>\n\n"
                "We encountered an issue while fetching the price data.\n"
                "Please try again in a moment."
            )
            
            if is_callback:
                try:
                    await update.callback_query.edit_message_text(
                        text=error_msg,
                        parse_mode='HTML',
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔄 Try Again", callback_data=f"price_{symbol}")],
                            [InlineKeyboardButton("❌ Close", callback_data="close")]
                        ])
                    )
                except Exception as edit_error:
                    logger.error(f"Error editing message: {edit_error}")
                    try:
                        await update.callback_query.answer("❌ Error: Could not update message")
                    except:
                        pass
            else:
                try:
                    await update.message.reply_text(
                        error_msg,
                        parse_mode='HTML',
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔄 Try Again", callback_data=f"price_{symbol}")],
                            [InlineKeyboardButton("❌ Close", callback_data="close")]
                        ])
                    )
                except Exception as send_error:
                    logger.error(f"Error sending error message: {send_error}")

    async def _coins_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1, is_callback: bool = False):
        """Handle /coins command with improved pagination"""
        try:
            # Get the message object based on whether this is a callback or command
            message = update.callback_query.message if is_callback else update.message
            
            # Get page number from command args if not provided
            if not is_callback and context.args:
                try:
                    page = max(1, int(context.args[0]))
                except (ValueError, IndexError):
                    pass
            
            per_page = 10  # Reduced number of coins per page for better readability
            
            # Show loading message
            loading_msg = None
            if not is_callback:  # Only show loading for initial command, not for callbacks
                loading_msg = await self._send_loading_message(update)
            
            # Get coins from service
            coins = await coin_service.get_coins(page=page, per_page=per_page)
            
            # Delete loading message if it exists
            if loading_msg:
                await self._delete_message_safe(loading_msg)
            
            if not coins:
                if is_callback:
                    await update.callback_query.answer("No more coins to show!")
                    return
                await update.message.reply_text("❌ No coins found. Please try again later.")
                return
            
            # Format message with better spacing and emojis
            message_text = [
                "<b>💰 Top Cryptocurrencies</b>\n",
                f"<i>Showing {len(coins)} coins • Page {page}</i>\n\n"
            ]
            
            for i, coin in enumerate(coins, 1):
                change_24h = coin.get('price_change_percentage_24h', 0)
                change_emoji = '🟢' if change_24h >= 0 else '🔴'
                
                message_text.append(
                    f"<b>{i + (page-1)*per_page}. {coin['name']} ({coin['symbol'].upper()})</b>\n"
                    f"   💵 Price: ${coin['current_price']:,.2f}\n"
                    f"   {change_emoji} 24h: {change_emoji} {abs(change_24h):.2f}%\n"
                    f"   📊 Market Cap: ${coin['market_cap']/1_000_000_000:,.2f}B\n"
                    f"   ──────────────────────────\n"
                )
            
            # Create inline keyboard with a single "Show More" button
            keyboard = []
            
            # Add Show More button if there are more coins to show
            if len(coins) == per_page:  # Only show if there might be more
                keyboard.append([
                    InlineKeyboardButton("🔄 Refresh", callback_data=f"coins_{page}"),
                    InlineKeyboardButton("Show More ➡️", callback_data=f"coins_{page+1}")
                ])
            else:
                keyboard.append([
                    InlineKeyboardButton("🔄 Refresh", callback_data=f"coins_{page}")
                ])
            
            reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
            
            # Join message parts
            message_text = "\n".join(message_text)
            
            # If it's a callback (pagination), edit the existing message
            if is_callback:
                try:
                    await update.callback_query.edit_message_text(
                        text=message_text,
                        parse_mode='HTML',
                        reply_markup=reply_markup
                    )
                    await update.callback_query.answer()
                except Exception as e:
                    logger.error(f"Error updating coins message: {e}")
                    await update.callback_query.answer("Failed to update. Please try again.")
            else:
                # Send new message for initial command
                await update.message.reply_text(
                    message_text,
                    parse_mode='HTML',
                    reply_markup=reply_markup,
                    disable_web_page_preview=True
                )

        except Exception as e:
            logger.error(f"Error in coins command: {e}")
            if 'loading_msg' in locals() and loading_msg:
                await self._delete_message_safe(loading_msg)
            
            error_msg = "❌ Failed to fetch coins. Please try again later."
            if is_callback:
                try:
                    await update.callback_query.answer(error_msg)
                except:
                    pass
            else:
                await update.message.reply_text(error_msg)

    async def _button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button callbacks"""
        query = update.callback_query
        await query.answer()
        
        if query.data.startswith('coins_'):
            # Handle coins pagination
            try:
                page = int(query.data.split('_')[1])
                # Call the coins command with the new page
                await self._coins_command(update, context, page=page, is_callback=True)
            except (ValueError, IndexError) as e:
                logger.error(f"Invalid page number in callback: {query.data}")
                await query.answer("❌ Invalid page number")
            except Exception as e:
                logger.error(f"Error in coins pagination: {e}")
                await query.answer("❌ Failed to load page")
        elif query.data == 'close':
            # Handle close button
            try:
                await query.message.delete()
            except Exception as e:
                logger.error(f"Error deleting message: {e}")
                await query.answer("❌ Failed to close message")

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
        """Handle /news command - Show detailed news with images and descriptions"""
        try:
            # Send typing action
            await update.message.chat.send_action(action='typing')
            
            # Get news items
            news_items = await news_service.get_news(limit=3)
            
            if not news_items:
                await update.message.reply_text("❌ No news available at the moment. Please try again later.")
                return

            # Send each news item as a separate message with image and description
            for item in news_items:
                # Escape special characters in title and description
                title = item.get('title', 'No title').replace('[', '\\[').replace('*', '\\*').replace('_', '\\_').replace('`', '\\`')
                description = item.get('description', '').replace('[', '\\[').replace('*', '\\*').replace('_', '\\_').replace('`', '\\`')
                
                # Create caption with source and description
                caption = (
                    f"<b>{title}</b>\n\n"
                    f"{description}\n\n"
                    f"📰 Source: {item.get('source', 'Unknown')}\n"
                    f"🔗 <a href='{item.get('url', '')}'>Read more</a>"
                )
                
                # Send photo with caption if image is available, otherwise send text
                if item.get('image'):
                    try:
                        await update.message.reply_photo(
                            photo=item['image'],
                            caption=caption,
                            parse_mode='HTML',
                            link_preview_options={"is_disabled": False}
                        )
                        continue
                    except Exception as e:
                        logger.warning(f"Failed to send photo: {e}")
                        # Fall back to text if photo fails
                
                # If no image or image failed to send, send text only
                await update.message.reply_text(
                    caption,
                    parse_mode='HTML',
                    link_preview_options={"is_disabled": False}
                )

        except Exception as e:
            logger.error(f"Error in news command: {e}")
            await update.message.reply_text("❌ Failed to fetch news. Please try again later.")
            
    async def _headlines_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /headlines command - Show top 5 headlines"""
        try:
            # Send typing action
            await update.message.chat.send_action(action='typing')
            
            # Get headlines
            headlines = await news_service.get_headlines(limit=5)
            
            if not headlines:
                await update.message.reply_text("❌ No headlines available at the moment. Please try again later.")
                return
            
            # Format headlines message
            message = ["<b>📰 Top Crypto Headlines:</b>\n"]
            for i, item in enumerate(headlines, 1):
                title = item.get('title', 'No title').replace('[', '\\[').replace('*', '\\*').replace('_', '\\_').replace('`', '\\`')
                message.append(f"{i}. <a href='{item.get('url', '')}'>{title}</a> - {item.get('source', 'Unknown')}")
            
            # Send the message
            await update.message.reply_text(
                '\n\n'.join(message),
                parse_mode='HTML',
                link_preview_options={"is_disabled": True}
            )
            
        except Exception as e:
            logger.error(f"Error in headlines command: {e}")
            await update.message.reply_text("❌ Failed to fetch headlines. Please try again later.")

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
                    "• /news - Latest market news with images\n"
                    "• /headlines - Top 5 crypto headlines"
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
                    "📰 /news - Latest crypto news with images\n"
                    "📰 /headlines - Top 5 crypto headlines\n"
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
                f"📰 /news - Get latest news with images"
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
            await db.disconnect()  # Close database connection
            await self.cache.close()
            
            logger.info("Telegram bot shut down successfully")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
            raise

# Create singleton instance
bot_instance = TelegramBot() 