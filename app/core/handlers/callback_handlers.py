from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from loguru import logger

# Import the command handlers that can be triggered by callbacks
from app.core.handlers.price_handlers import price_command, coins_command, price_history_command

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, price_service_instance, coin_service_instance):
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()
    
    try:
        if query.data.startswith('coins_'):
            # Handle coins pagination
            try:
                page = int(query.data.split('_')[1])
                await coins_command(update, context, coin_service_instance, is_callback=True, page=page)
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
                await price_history_command(update, context, price_service_instance, symbol, days, is_callback=True)
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
                await price_command(update, context, price_service_instance, symbol=symbol, is_callback=True)
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