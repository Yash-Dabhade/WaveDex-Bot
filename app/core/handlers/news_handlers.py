from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from loguru import logger

# Assume news_service is available via context or passed as an argument
async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE, news_service_instance):
    """Handle /news command - Show detailed news with images and descriptions"""
    try:
        # Send typing action - This is used instead of a "please wait" message
        await update.message.chat.send_action(action='typing')
        
        # Get news items
        news_items = await news_service_instance.get_news(limit=3)
        
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
        
async def headlines_command(update: Update, context: ContextTypes.DEFAULT_TYPE, news_service_instance):
    """Handle /headlines command - Show top 5 headlines"""
    try:
        # Send typing action - This is used instead of a "please wait" message
        await update.message.chat.send_action(action='typing')
        
        # Get headlines
        headlines = await news_service_instance.get_headlines(limit=5)
        
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
