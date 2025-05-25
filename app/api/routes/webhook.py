from fastapi import APIRouter, Response
from loguru import logger

router = APIRouter()

@router.post("")
async def telegram_webhook():
    """Placeholder route - Bot is using polling mode"""
    return Response(
        status_code=400,
        content="Bot is configured to use polling mode. Webhook endpoints are disabled."
    )