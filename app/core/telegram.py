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
            ("headlines", "Get top 5 crypto headlines", self._headlines_command),
            ("news", "Get latest crypto news with images and descriptions", self._news_command),
            ("setalert", "Set price alert", self._set_alert_command),
            ("alerts", "View your active alerts", self._list_alerts_command),
            ("delalert", "Delete an alert", self._delete_alert_command)
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
        
        try:
            if query.data.startswith('coins_'):
                # Handle coins pagination
                try:
                    page = int(query.data.split('_')[1])
                    await self._coins_command(update, context, page=page, is_callback=True)
                except (ValueError, IndexError) as e:
                    logger.error(f"Invalid page number in callback: {query.data}")
                    await query.answer("❌ Invalid page number")
                except Exception as e:
                    logger.error(f"Error in coins pagination: {e}")
                    await query.answer("❌ Failed to load page")
            
            elif query.data.startswith('history_'):
                # Handle history time period selection
                try:
                    parts = query.data.split('_')
                    symbol = parts[1]
                    days = int(parts[2]) if len(parts) > 2 else 7
                    await self._price_history_command(update, context, symbol, days, is_callback=True)
                except (ValueError, IndexError) as e:
                    logger.error(f"Invalid history parameters in callback: {query.data}")
                    await query.answer("❌ Invalid parameters")
                except Exception as e:
                    logger.error(f"Error in history callback: {e}")
                    await query.answer("❌ Failed to load history")
            
            elif query.data.startswith('price_'):
                # Handle price refresh from button
                try:
                    symbol = query.data.split('_')[1]
                    await self._price_command(update, context, symbol=symbol, is_callback=True)
                except (ValueError, IndexError) as e:
                    logger.error(f"Invalid price parameters in callback: {query.data}")
                    await query.answer("❌ Invalid parameters")
                except Exception as e:
                    logger.error(f"Error in price callback: {e}")
                    await query.answer("❌ Failed to load price")
            
            elif query.data == 'close':
                # Handle close button
                try:
                    await query.message.delete()
                except Exception as e:
                    logger.error(f"Error deleting message: {e}")
                    await query.answer("❌ Failed to close message")
            
            else:
                await query.answer("⚠️ This button doesn't do anything yet!")
        
        except Exception as e:
            logger.error(f"Error in button callback: {e}", exc_info=True)
            try:
                await query.answer("❌ An error occurred. Please try again.")
            except:
                pass

    async def _price_history_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE, symbol: str = None, days: int = 7, is_callback: bool = False):
        """Handle /history command with improved formatting and navigation"""
        try:
            # Get message object based on whether this is a callback or command
            message = update.callback_query.message if is_callback else update.message
            
            # Get symbol and days from command args if not provided
            if not symbol or not is_callback:
                if not context.args:
                    await message.reply_text(
                        "📈 <b>Price History</b>\n\n"
                        "Please provide a cryptocurrency symbol.\n"
                        "Example: <code>/history btc 7</code>\n"
                        "(7 days is default if no number is provided)",
                        parse_mode='HTML'
                    )
                    return
                
                symbol = context.args[0].lower()
                if len(context.args) > 1:
                    try:
                        days = int(context.args[1])
                        if not 1 <= days <= 30:
                            raise ValueError("Days must be between 1 and 30")
                    except ValueError:
                        await message.reply_text(
                            "❌ <b>Invalid number of days</b>\n\n"
                            "Please provide a number between 1 and 30.\n"
                            "Example: <code>/history btc 7</code>",
                            parse_mode='HTML'
                        )
                        return

            # Show loading message
            loading_msg = None
            if not is_callback:
                loading_msg = await self._send_loading_message(update)

            # Get historical data
            history_data = await price_service.get_price_history(symbol, days)
            await self._delete_message_safe(loading_msg)

            if not history_data or 'error' in history_data:
                error_msg = (
                    f"❌ <b>History Not Available</b>\n\n"
                    f"Could not fetch history for <code>{symbol.upper()}</code>.\n"
                    f"Error: {history_data.get('error', 'Unknown error') if history_data else 'No data'}"
                )
                
                if is_callback:
                    await update.callback_query.edit_message_text(
                        text=error_msg,
                        parse_mode='HTML',
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔄 Try Again", callback_data=f"history_{symbol}_{days}")],
                            [InlineKeyboardButton("🔙 Back", callback_data=f"price_{symbol}")]
                        ])
                    )
                else:
                    await message.reply_text(
                        error_msg,
                        parse_mode='HTML',
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔄 Try Again", callback_data=f"history_{symbol}_{days}")],
                            [InlineKeyboardButton("🔙 Back", callback_data=f"price_{symbol}")]
                        ])
                    )
                return

            # Format the history data
            symbol = history_data.get('symbol', symbol.upper())
            history = history_data.get('history', [])

            if not history:
                no_data_msg = f"❌ No historical data available for {symbol}"
                if is_callback:
                    await update.callback_query.edit_message_text(
                        text=no_data_msg,
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔙 Back", callback_data=f"price_{symbol}")]
                        ])
                    )
                else:
                    await message.reply_text(no_data_msg)
                return

            # Calculate price change for the period
            first_price = history[0].get('price', 0) if history else 0
            last_price = history[-1].get('price', 0) if history else 0
            price_change = ((last_price - first_price) / first_price * 100) if first_price else 0
            change_emoji = '🟢' if price_change >= 0 else '🔴'

            # Format the message
            message_text = (
                f"📈 <b>{symbol} Price History</b>\n"
                f"<code>────────────────────</code>\n"
                f"📅 <b>Period:</b> {days} day{'s' if days > 1 else ''}\n"
                f"💰 <b>Current Price:</b> ${last_price:,.2f}\n"
                f"{change_emoji} <b>Period Change:</b> {change_emoji} {abs(price_change):.2f}%\n"
                f"📊 <b>Data Points:</b> {len(history)}\n"
                f"<code>────────────────────</code>\n"
                f"📅 <b>Latest Data Points:</b>\n"
            )

            # Add last 5 data points (or all if less than 5)
            for i, point in enumerate(history[-5:], 1):
                timestamp = point.get('timestamp', 0) / 1000  # Convert from ms to seconds if needed
                date = datetime.fromtimestamp(timestamp).strftime('%b %d, %H:%M')
                price = point.get('price', 0)
                message_text += f"• {date}: <b>${price:,.2f}</b>\n"

            # Create inline keyboard with time period options
            keyboard = [
                [
                    InlineKeyboardButton("24h", callback_data=f"history_{symbol}_1"),
                    InlineKeyboardButton("7d", callback_data=f"history_{symbol}_7"),
                    InlineKeyboardButton("30d", callback_data=f"history_{symbol}_30")
                ],
                [
                    InlineKeyboardButton("🔙 Back to Price", callback_data=f"price_{symbol}"),
                    InlineKeyboardButton("❌ Close", callback_data="close")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            if is_callback:
                await update.callback_query.edit_message_text(
                    text=message_text,
                    parse_mode='HTML',
                    reply_markup=reply_markup
                )
                await update.callback_query.answer()
            else:
                await message.reply_text(
                    message_text,
                    parse_mode='HTML',
                    reply_markup=reply_markup,
                    disable_web_page_preview=True
                )

        except ValueError as ve:
            error_msg = (
                "❌ <b>Invalid Input</b>\n\n"
                f"{str(ve)}\n\n"
                "Please provide a valid number between 1 and 30 for days.\n"
                "Example: <code>/history btc 7</code>"
            )
            if is_callback:
                await update.callback_query.answer(str(ve))
            else:
                await message.reply_text(error_msg, parse_mode='HTML')
                
        except Exception as e:
            logger.error(f"Error in history command: {e}", exc_info=True)
            error_msg = "❌ Failed to fetch price history. Please try again later."
            
            if is_callback:
                try:
                    await update.callback_query.edit_message_text(
                        text=error_msg,
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔄 Try Again", callback_data=f"history_{symbol}_{days}")],
                            [InlineKeyboardButton("❌ Close", callback_data="close")]
                        ])
                    )
                except Exception as edit_error:
                    logger.error(f"Error editing message: {edit_error}")
                    await update.callback_query.answer("❌ Error: Could not update message")
            else:
                await message.reply_text(error_msg)

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
                    disable_web_page_preview=False
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
                disable_web_page_preview=True
            )
            
        except Exception as e:
            logger.error(f"Error in headlines command: {e}")
            await update.message.reply_text("❌ Failed to fetch headlines. Please try again later.")

    async def _set_alert_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /setalert command with improved validation and feedback"""
        loading_msg = await update.message.reply_text("⏳ Setting up your alert...")
        
        try:
            # Show help if no arguments provided
            if not context.args or len(context.args) < 3:
                help_text = (
                    "🔔 *Set Price Alert* 🔔\n\n"
                    "*Usage:* `/setalert <symbol> <price> <above|below>`\n"
                    "*Example:* `/setalert BTC 50000 above`\n\n"
                    "*Parameters:*\n"
                    "• `<symbol>` - Cryptocurrency symbol (e.g., BTC, ETH)\n"
                    "• `<price>` - Target price to be notified at\n"
                    "• `<above|below>` - Whether to alert when price goes above or below the target\n\n"
                    "*Example Usage:*\n"
                    "• `/setalert BTC 50000 above` - Alert when BTC goes above $50,000\n"
                    "• `/setalert ETH 2000 below` - Alert when ETH drops below $2,000"
                )
                await self._delete_message_safe(loading_msg)
                await update.message.reply_text(
                    help_text,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True
                )
                return

            # Parse and validate input
            symbol = context.args[0].upper()
            try:
                price = float(context.args[1].replace(',', ''))
                if price <= 0:
                    raise ValueError("Price must be greater than 0")
                condition = context.args[2].lower()
                if condition not in ['above', 'below']:
                    raise ValueError("Invalid condition")
            except ValueError as e:
                error_msg = ""
                if "could not convert string to float" in str(e):
                    error_msg = "❌ Invalid price format. Please enter a valid number."
                elif "Price must be greater than 0" in str(e):
                    error_msg = "❌ Price must be greater than 0."
                elif "Invalid condition" in str(e):
                    error_msg = "❌ Condition must be either 'above' or 'below'."
                else:
                    error_msg = "❌ Invalid input. Please check your values and try again."
                
                await self._delete_message_safe(loading_msg)
                await update.message.reply_text(
                    f"{error_msg}\n\n"
                    "*Example:* `/setalert BTC 50000 above`",
                    parse_mode=ParseMode.MARKDOWN
                )
                return

            # Set the alert
            result = await alert_service.set_alert(
                user_id=update.effective_user.id,
                symbol=symbol,
                target_price=price,
                condition=condition
            )

            # Handle response
            if 'error' in result:
                error_msg = result['error']
                if 'duplicate' in error_msg.lower():
                    response = "ℹ️ You already have a similar alert set."
                else:
                    response = f"❌ {error_msg}"
                
                await self._delete_message_safe(loading_msg)
                await update.message.reply_text(
                    response,
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                # Get current price for feedback
                current_price = await price_service.get_current_price(symbol)
                price_diff = ((current_price - price) / price * 100) if current_price else 0
                
                response = (
                    f"✅ *Alert Set Successfully* ✅\n\n"
                    f"• *Symbol:* {symbol}\n"
                    f"• *Condition:* Price {condition.upper()} ${price:,.2f}\n"
                    f"• *Current Price:* ${current_price:,.2f} ({price_diff:+.2f}%)"
                )
                
                await self._delete_message_safe(loading_msg)
                await update.message.reply_text(
                    response,
                    parse_mode=ParseMode.MARKDOWN
                )
                
        except Exception as e:
            logger.error(f"Error in set_alert_command: {e}")
            await self._delete_message_safe(loading_msg)
            await update.message.reply_text(
                "❌ An error occurred while setting the alert. Please try again.",
                parse_mode=ParseMode.MARKDOWN
            )

    async def _list_alerts_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /alerts command with improved formatting and current prices"""
        loading_msg = await update.message.reply_text("⏳ Fetching your alerts...")
        
        try:
            # Get user's alerts
            alerts = await alert_service.get_user_alerts(update.effective_user.id)
            
            if not alerts:
                no_alerts_msg = (
                    "🔕 *No Active Alerts*\n\n"
                    "You don't have any active price alerts.\n"
                    "Use `/setalert <symbol> <price> <above|below>` to create one!"
                )
                await update.message.reply_text(
                    no_alerts_msg,
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            # Get unique symbols to fetch current prices
            symbols = list({alert['symbol'].upper() for alert in alerts})
            current_prices = await price_service.get_prices(symbols)
            
            # Format alerts with current prices
            alert_messages = []
            for alert in alerts:
                symbol = alert['symbol'].upper()
                current_price = current_prices.get(symbol, {}).get('price', alert.get('current_price', 0))
                target_price = alert['target_price']
                price_diff = ((current_price - target_price) / target_price * 100) if target_price else 0
                
                # Determine alert status emoji
                status_emoji = "🟢"  # Default: alert not triggered
                if alert.get('triggered'):
                    status_emoji = "🔴"  # Alert triggered
                
                # Create progress bar (20 characters wide)
                progress = min(1.0, max(0.0, current_price / (target_price * 1.5)))
                progress_bar = "█" * int(progress * 20)
                progress_bar = progress_bar.ljust(20, "░")
                
                # Format alert message
                alert_msg = (
                    f"{status_emoji} *{symbol}*\n"
                    f"`{progress_bar}`\n"
                    f"• Target: ${target_price:,.2f} ({alert['condition']})\n"
                    f"• Current: ${current_price:,.2f} ({price_diff:+.2f}%)"
                )
                
                # Add alert ID for reference
                alert_msg += f"\n• ID: `{alert['id']}`"
                
                alert_messages.append(alert_msg)
            
            # Create paginated messages (max 5 alerts per message)
            max_alerts_per_message = 5
            for i in range(0, len(alert_messages), max_alerts_per_message):
                chunk = alert_messages[i:i + max_alerts_per_message]
                message = "🔔 *Your Alerts* 🔔\n\n"
                message += "\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n".join(chunk)
                
                # Add footer to the last message
                if i + max_alerts_per_message >= len(alert_messages):
                    message += "\n\nUse `/delalert <id>` to remove an alert."
                
                await update.message.reply_text(
                    message,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True
                )
                
        except Exception as e:
            logger.error(f"Error in alerts command: {e}")
            await update.message.reply_text(
                "❌ Failed to fetch alerts. Please try again later.",
                parse_mode=ParseMode.MARKDOWN
            )
        finally:
            await self._delete_message_safe(loading_msg)

    async def _delete_alert_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /delalert command with improved feedback and confirmation"""
        loading_msg = await update.message.reply_text("⏳ Processing your request...")
        
        try:
            # Validate command arguments
            if not context.args:
                help_text = (
                    "🗑 *Delete Alert* 🗑\n\n"
                    "*Usage:* `/delalert <alert_id>`\n"
                    "*Example:* `/delalert 12345`\n\n"
                    "Use `/alerts` to see your active alerts and their IDs."
                )
                await update.message.reply_text(
                    help_text,
                    parse_mode=ParseMode.MARKDOWN
                )
                await self._delete_message_safe(loading_msg)
                return
                
            alert_id = context.args[0]
            
            # First, get the alert details to show what's being deleted
            alerts = await alert_service.get_user_alerts(update.effective_user.id)
            alert_to_delete = next((a for a in alerts if str(a['id']) == alert_id), None)
            
            if not alert_to_delete:
                await update.message.reply_text(
                    "❌ Alert not found. Please check the alert ID and try again.\n"
                    "Use `/alerts` to see your active alerts.",
                    parse_mode=ParseMode.MARKDOWN
                )
                await self._delete_message_safe(loading_msg)
                return
            
            # Delete the alert
            result = await alert_service.delete_alert(
                user_id=update.effective_user.id,
                alert_id=alert_id
            )
            
            if 'error' in result:
                await update.message.reply_text(
                    f"❌ {result['error']}",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                # Format success message with alert details
                symbol = alert_to_delete['symbol'].upper()
                target_price = alert_to_delete['target_price']
                condition = alert_to_delete['condition']
                
                success_msg = (
                    f"🗑 *Alert Deleted* ✅\n\n"
                    f"• *Symbol:* {symbol}\n"
                    f"• *Condition:* Price {condition.upper()} ${target_price:,.2f}\n"
                    f"• *Alert ID:* `{alert_id}`"
                )
                
                await update.message.reply_text(
                    success_msg,
                    parse_mode=ParseMode.MARKDOWN
                )
                
        except Exception as e:
            logger.error(f"Error in delalert command: {e}")
            await update.message.reply_text(
                "❌ Failed to delete alert. Please try again later.",
                parse_mode=ParseMode.MARKDOWN
            )
        finally:
            await self._delete_message_safe(loading_msg)

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
                    change_24h = alert.get('price_data', {}).get('change_24h', 0)
                    high_24h = alert.get('price_data', {}).get('high_24h', 0)
                    low_24h = alert.get('price_data', {}).get('low_24h', 0)
                    
                    # Determine direction emoji and status
                    direction_emoji = '📈' if condition == 'above' else '📉'
                    status_emoji = '🎯'  # Default status emoji
                    
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