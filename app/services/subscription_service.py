from typing import List, Dict, Optional
from loguru import logger
from datetime import datetime

from app.core.db import db
from app.services.news_service import news_service
from app.services.notification_service import notification_service
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
            user = await db.prisma.user.find_unique(
                where={"id": user_id},
                include={"subscription_tier": True}
            )
            if not user:
                raise ValueError("User not found")

            # Check if user has reached subscription limit for their tier
            current_count = await db.prisma.subscription.count(
                where={"userId": user_id}
            )
            max_subscriptions = user.subscription_tier.max_subscriptions

            if current_count >= max_subscriptions:
                raise ValueError(
                    f"Subscription limit reached for {user.subscription_tier.name} tier. "
                    f"Current: {current_count}, Max: {max_subscriptions}"
                )

            # Create subscription
            subscription = await db.prisma.subscription.create(
                data={
                    "userId": user_id,
                    "symbol": symbol.upper(),
                    "createdAt": datetime.utcnow()
                }
            )
            return Subscription.from_orm(subscription)

        except Exception as e:
            logger.error(f"Error creating subscription: {e}")
            raise

    async def get_user_subscriptions(self, user_id: str) -> List[Subscription]:
        """Get all subscriptions for a user"""
        try:
            subscriptions = await db.prisma.subscription.find_many(
                where={"userId": user_id}
            )
            return [Subscription.from_orm(sub) for sub in subscriptions]
        except Exception as e:
            logger.error(f"Error getting user subscriptions: {e}")
            raise

    async def delete_subscription(self, user_id: str, symbol: str):
        """Delete a subscription"""
        try:
            await db.prisma.subscription.delete_many(
                where={
                    "userId": user_id,
                    "symbol": symbol.upper()
                }
            )
        except Exception as e:
            logger.error(f"Error deleting subscription: {e}")
            raise

    async def send_news_updates(self):
        """Send news updates to subscribed users"""
        try:
            # Get all active subscriptions with news enabled
            subscriptions = await db.prisma.subscription.find_many(
                where={"newsEnabled": True},
                include={"user": True}
            )

            # Group subscriptions by symbol
            symbol_subs: Dict[str, List[Dict]] = {}
            for sub in subscriptions:
                if sub.symbol not in symbol_subs:
                    symbol_subs[sub.symbol] = []
                symbol_subs[sub.symbol].append({"user": sub.user, "symbol": sub.symbol})
                symbol_subs[sub.symbol].append(sub)

            # Process each symbol
            for symbol, subs in symbol_subs.items():
                # Get latest news for symbol
                news_items = await news_service.get_news(symbol)
                if not news_items:
                    continue

                # Get most recent news item
                latest_news = news_items[0]

                # Send update to each subscriber
                for sub in subs:
                    # Skip if we've already sent this update
                    if sub.get('lastNewsId') == latest_news.id:
                        continue

                    # Send notification
                    await notification_service.send_news_update(
                        user_id=sub['user'].id,
                        symbol=symbol,
                        news_item=latest_news
                    )

                    # Update last sent news ID
                    await db.prisma.subscription.update_many(
                        where={
                            "userId": sub['user'].id,
                            "symbol": symbol
                        },
                        data={"lastNewsId": latest_news.id}
                    )

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
        # Notification service will log if bot is not initialized
        for sub in subscriptions:
            try:
                # Format message
                message = self._format_news_message(symbol, news_items)

                # Send message
                await notification_service.send_message(
                    chat_id=sub.user.telegramId,
                    text=message
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
            SubscriptionTier.FREE: 10,
            SubscriptionTier.PREMIUM: 50,
            SubscriptionTier.PRO: 999
        }
        return limits.get(tier, 10)

# Create singleton instance
subscription_service = SubscriptionService() 