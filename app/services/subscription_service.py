from typing import List, Dict, Optional
from loguru import logger
from datetime import datetime

from app.services.prisma_service import prisma_service
from app.services.news_service import news_service
from app.core.telegram import bot_instance
from app.models.schemas import Subscription, NewsItem, SubscriptionTier

class SubscriptionService:
    _instance: Optional['SubscriptionService'] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SubscriptionService, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._initialized = True

    async def create_subscription(self, user_id: str, symbol: str) -> Subscription:
        """Create a new subscription"""
        try:
            # Check subscription limits
            user = await prisma_service.get_user_by_id(user_id)
            if not user:
                raise ValueError("User not found")

            current_subs = await self.get_user_subscriptions(user_id)
            
            # Check subscription limits based on tier
            max_subs = self._get_max_subscriptions(user["subscriptionTier"])
            if len(current_subs) >= max_subs:
                raise ValueError(
                    f"Subscription limit reached for {user['subscriptionTier']} tier. "
                    f"Max: {max_subs}"
                )

            subscription = await prisma_service.create_subscription(
                user_id=user_id,
                symbol=symbol
            )
            return Subscription.from_orm(subscription)

        except Exception as e:
            logger.error(f"Error creating subscription: {e}")
            raise

    async def get_user_subscriptions(self, user_id: str) -> List[Subscription]:
        """Get all subscriptions for a user"""
        try:
            subscriptions = await prisma_service.get_user_subscriptions(user_id)
            return [Subscription.from_orm(sub) for sub in subscriptions]
        except Exception as e:
            logger.error(f"Error getting user subscriptions: {e}")
            raise

    async def delete_subscription(self, user_id: str, symbol: str):
        """Delete a subscription"""
        try:
            await prisma_service.delete_subscription(user_id, symbol)
        except Exception as e:
            logger.error(f"Error deleting subscription: {e}")
            raise

    async def send_news_updates(self, force_refresh: bool = False):
        """Send news updates to subscribed users"""
        try:
            # Get all active subscriptions with news enabled
            async with prisma_service.get_connection() as db:
                subscriptions = await db.subscription.find_many(
                    where={"newsEnabled": True},
                    include={"user": True}
                )

            # Group subscriptions by symbol
            symbol_subs: Dict[str, List[Dict]] = {}
            for sub in subscriptions:
                if sub.symbol not in symbol_subs:
                    symbol_subs[sub.symbol] = []
                symbol_subs[sub.symbol].append(sub)

            # Process each symbol
            for symbol, subs in symbol_subs.items():
                try:
                    # Get latest news
                    news_items = await news_service.get_news(
                        symbol,
                        force_refresh=force_refresh
                    )

                    if not news_items:
                        continue

                    # Send updates to subscribed users
                    await self._send_news_to_subscribers(symbol, news_items, subs)

                except Exception as e:
                    logger.error(f"Error processing news for {symbol}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error sending news updates: {e}")
            raise

    async def _send_news_to_subscribers(
        self,
        symbol: str,
        news_items: List[NewsItem],
        subscriptions: List[Dict]
    ):
        """Send news updates to subscribers"""
        if not bot_instance.bot:
            logger.error("Telegram bot not initialized")
            return

        for sub in subscriptions:
            try:
                # Format message
                message = self._format_news_message(symbol, news_items)

                # Send message
                await bot_instance.bot.send_message(
                    chat_id=sub.user.telegramId,
                    text=message,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )

            except Exception as e:
                logger.error(f"Error sending news to user {sub.user.telegramId}: {e}")
                continue

    def _format_news_message(self, symbol: str, news_items: List[NewsItem]) -> str:
        """Format news items into a message"""
        message = f"📰 Latest News for {symbol}\n\n"

        for item in news_items[:5]:  # Limit to 5 news items
            sentiment = ""
            if item.sentiment is not None:
                if item.sentiment > 0.2:
                    sentiment = "🟢"
                elif item.sentiment < -0.2:
                    sentiment = "🔴"
                else:
                    sentiment = "⚪️"

            message += (
                f"{sentiment} <b>{item.title}</b>\n"
                f"Source: {item.source}\n"
                f"<a href='{item.url}'>Read more</a>\n\n"
            )

        return message

    def _get_max_subscriptions(self, tier: str) -> int:
        """Get maximum allowed subscriptions for tier"""
        limits = {
            SubscriptionTier.FREE: 3,
            SubscriptionTier.PREMIUM: 10,
            SubscriptionTier.PRO: 999
        }
        return limits.get(tier, 3)

# Create singleton instance
subscription_service = SubscriptionService() 