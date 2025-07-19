from telegram import Update, Message
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from loguru import logger
from typing import Optional

# Assume alert_service and price_service are available via context or passed as arguments
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

async def set_alert_command(update: Update, context: ContextTypes.DEFAULT_TYPE, alert_service_instance, price_service_instance):
    """Handle /setalert command with improved validation and feedback"""
    loading_msg = await _send_loading_message(update)
    
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
            await _delete_message_safe(loading_msg)
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
            
            await _delete_message_safe(loading_msg)
            await update.message.reply_text(
                f"{error_msg}\n\n"
                "*Example:* `/setalert BTC 50000 above`",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        # Set the alert
        result = await alert_service_instance.set_alert(
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
            
            await _delete_message_safe(loading_msg)
            await update.message.reply_text(
                response,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            # Get current price for feedback
            current_price = await price_service_instance.get_current_price(symbol)
            price_diff = ((current_price - price) / price * 100) if current_price else 0
            
            response = (
                f"✅ *Alert Set Successfully* ✅\n\n"
                f"• *Symbol:* {symbol}\n"
                f"• *Condition:* Price {condition.upper()} ${price:,.2f}\n"
                f"• *Current Price:* ${current_price:,.2f} ({price_diff:+.2f}%)"
            )
            
            await _delete_message_safe(loading_msg)
            await update.message.reply_text(
                response,
                parse_mode=ParseMode.MARKDOWN
            )
            
    except Exception as e:
        logger.error(f"Error in set_alert_command: {e}")
        await _delete_message_safe(loading_msg)
        await update.message.reply_text(
            "❌ An error occurred while setting the alert. Please try again.",
            parse_mode=ParseMode.MARKDOWN
        )

async def list_alerts_command(update: Update, context: ContextTypes.DEFAULT_TYPE, alert_service_instance, price_service_instance):
    """Handle /alerts command with improved formatting and current prices"""
    loading_msg = await _send_loading_message(update)
    
    try:
        # Get user's alerts
        alerts = await alert_service_instance.get_user_alerts(update.effective_user.id)
        
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
        current_prices = await price_service_instance.get_prices(symbols)
        
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
        await _delete_message_safe(loading_msg)

async def delete_alert_command(update: Update, context: ContextTypes.DEFAULT_TYPE, alert_service_instance):
    """Handle /delalert command with improved feedback and confirmation"""
    loading_msg = await _send_loading_message(update)
    
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
            await _delete_message_safe(loading_msg)
            return
            
        alert_id = context.args[0]
        
        # First, get the alert details to show what's being deleted
        alerts = await alert_service_instance.get_user_alerts(update.effective_user.id)
        alert_to_delete = next((a for a in alerts if str(a['id']) == alert_id), None)
        
        if not alert_to_delete:
            await update.message.reply_text(
                "❌ Alert not found. Please check the alert ID and try again.\n"
                "Use `/alerts` to see your active alerts.",
                parse_mode=ParseMode.MARKDOWN
            )
            await _delete_message_safe(loading_msg)
            return
        
        # Delete the alert
        result = await alert_service_instance.delete_alert(
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
        await _delete_message_safe(loading_msg)