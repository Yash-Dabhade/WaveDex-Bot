from telegram import Update, Message, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from loguru import logger
from typing import Optional
from datetime import datetime

# Assume price_service is available via context or passed as an argument
# For this example, we'll pass the necessary functions from TelegramBot class
async def _send_loading_message(update: Update) -> Optional[Message]:
    """Send a loading message and return it for later deletion"""
    try:
        return await update.message.reply_text("⏳ Processing your request...")
    except Exception as e:
        logger.error(f"Error sending loading message: {e}")
        return None

async def _delete_message_safe(message: Optional[Message]):
    """Safely delete a message"""
    if message:
        try:
            await message.delete()
        except Exception as e:
            logger.error(f"Error deleting message: {e}")

async def price_command(update: Update, context: ContextTypes.DEFAULT_TYPE, price_service_instance, symbol: str = None, is_callback: bool = False):
    """Handle /price command with improved formatting"""
    loading_msg = None
    try:
        # Get symbol from callback or command args
        if not symbol:
            if not context.args:
                reply_target = update.callback_query.message if is_callback else update.message
                await reply_target.reply_text(
                    "💱 <b>Price Check</b>\n\n"
                    "Please provide a cryptocurrency symbol.\n"
                    "Example: <code>/price btc</code>\n"
                    "Use /coins to see supported cryptocurrencies",
                    parse_mode='HTML'
                )
                if is_callback:
                    await update.callback_query.answer()
                return
            symbol = context.args[0].lower()

        # Show loading message
        if not is_callback:
            loading_msg = await _send_loading_message(update)

        # Get price data
        price_data = await price_service_instance.get_price(symbol)
        await _delete_message_safe(loading_msg)

        if not price_data or 'error' in price_data:
            error_msg = (
                f"❌ <b>Symbol Not Found</b>\n\n"
                f"Could not find data for <code>{symbol.upper()}</code>.\n"
                f"Error: {price_data.get('error', 'Unknown error')}\n\n"
                "Please check the symbol and try again.\n"
                "Use /coins to see supported cryptocurrencies"
            )
            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Try Again", callback_data=f"price_{symbol}")],
                [InlineKeyboardButton("❌ Close", callback_data="close")]
            ])
            if is_callback:
                await update.callback_query.edit_message_text(
                    text=error_msg,
                    parse_mode='HTML',
                    reply_markup=reply_markup
                )
                await update.callback_query.answer()
            else:
                await update.message.reply_text(
                    error_msg,
                    parse_mode='HTML',
                    reply_markup=reply_markup
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
        await _delete_message_safe(loading_msg)
        
        error_msg = (
            "❌ <b>Error fetching price data</b>\n\n"
            "We encountered an issue while fetching the price data.\n"
            "Please try again in a moment."
        )
        
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Try Again", callback_data=f"price_{symbol}")],
            [InlineKeyboardButton("❌ Close", callback_data="close")]
        ])
        
        if is_callback:
            try:
                await update.callback_query.edit_message_text(
                    text=error_msg,
                    parse_mode='HTML',
                    reply_markup=reply_markup
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
                    reply_markup=reply_markup
                )
            except Exception as send_error:
                logger.error(f"Error sending error message: {send_error}")

async def coins_command(update: Update, context: ContextTypes.DEFAULT_TYPE, coin_service_instance, is_callback: bool = False, page: int = 1):
    """Handle /coins command with improved pagination"""
    loading_msg = None
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
        if not is_callback:  # Only show loading for initial command, not for callbacks
            loading_msg = await _send_loading_message(update)
        
        # Get coins from service
        coins = await coin_service_instance.get_coins(page=page, per_page=per_page)
        
        # Delete loading message if it exists
        await _delete_message_safe(loading_msg)
        
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
        await _delete_message_safe(loading_msg)
        
        error_msg = "❌ Failed to fetch coins. Please try again later."
        if is_callback:
            try:
                await update.callback_query.answer(error_msg)
            except:
                pass
        else:
            await update.message.reply_text(error_msg)

async def price_history_command(update: Update, context: ContextTypes.DEFAULT_TYPE, price_service_instance, symbol: str = None, days: int = 7, is_callback: bool = False):
    """Handle /history command with improved formatting and navigation"""
    loading_msg = None
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
        if not is_callback:
            loading_msg = await _send_loading_message(update)

        # Get historical data
        history_data = await price_service_instance.get_price_history(symbol, days)
        await _delete_message_safe(loading_msg)

        if not history_data or 'error' in history_data:
            error_msg = (
                f"❌ <b>History Not Available</b>\n\n"
                f"Could not fetch history for <code>{symbol.upper()}</code>.\n"
                f"Error: {history_data.get('error', 'Unknown error') if history_data else 'No data'}"
            )
            
            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Try Again", callback_data=f"history_{symbol}_{days}")],
                [InlineKeyboardButton("🔙 Back", callback_data=f"price_{symbol}")]
            ])

            if is_callback:
                await update.callback_query.edit_message_text(
                    text=error_msg,
                    parse_mode='HTML',
                    reply_markup=reply_markup
                )
            else:
                await message.reply_text(
                    error_msg,
                    parse_mode='HTML',
                    reply_markup=reply_markup
                )
            return

        # Format the history data
        symbol = history_data.get('symbol', symbol.upper())
        history = history_data.get('history', [])

        if not history:
            no_data_msg = f"❌ No historical data available for {symbol}"
            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data=f"price_{symbol}")]
            ])
            if is_callback:
                await update.callback_query.edit_message_text(
                    text=no_data_msg,
                    reply_markup=reply_markup
                )
            else:
                await message.reply_text(no_data_msg, reply_markup=reply_markup)
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
        await _delete_message_safe(loading_msg)
        if is_callback:
            await update.callback_query.answer(str(ve))
        else:
            await message.reply_text(error_msg, parse_mode='HTML')
            
    except Exception as e:
        logger.error(f"Error in history command: {e}", exc_info=True)
        await _delete_message_safe(loading_msg)
        error_msg = "❌ Failed to fetch price history. Please try again later."
        
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Try Again", callback_data=f"history_{symbol}_{days}")],
            [InlineKeyboardButton("❌ Close", callback_data="close")]
        ])

        if is_callback:
            try:
                await update.callback_query.edit_message_text(
                    text=error_msg,
                    reply_markup=reply_markup
                )
            except Exception as edit_error:
                logger.error(f"Error editing message: {edit_error}")
                await update.callback_query.answer("❌ Error: Could not update message")
        else:
            await message.reply_text(error_msg)