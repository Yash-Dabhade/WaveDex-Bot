from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from loguru import logger

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    welcome_message = (
        "👋 Welcome to CryptoTracker!\n\n"
        "I can help you track crypto prices, manage your portfolio, "
        "and stay updated with market movements.\n\n"
        "Use /help to see available commands."
    )
    await update.message.reply_text(welcome_message)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    help_message = (
        "📱 Available Commands:\n\n"
        "💰 Prices & Market\n"
        "/price [symbol] - Current price & stats\n"
        "/coins - List supported coins\n"
        "/history [symbol] [days] - Price history\n"
        "⚡️ Alerts\n"
        "/setalert [symbol] [price] [above/below] - Set alert\n"
        "/alerts - View your alerts\n"
        "/delalert [id] - Delete alert\n\n"
        "📰 News\n"
        "/news - Latest crypto news with images and descriptions\n"
        "/headlines - Top 5 crypto headlines\n\n"
        "💼 Portfolio\n"
        "/portfolio - View your portfolio\n"
        "/add [symbol] [quantity] [price] - Add a position\n"
        "/remove [symbol] [quantity] - Remove a position\n"
        "/trending - View trending coins"
    )
    await update.message.reply_text(help_message)