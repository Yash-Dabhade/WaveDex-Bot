from prisma import Prisma
from typing import Optional, Any, Dict, List
from loguru import logger
import contextlib

class PrismaService:
    _instance: Optional['PrismaService'] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PrismaService, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self.db = Prisma()
            self._initialized = True

    async def connect(self):
        """Connect to database"""
        try:
            await self.db.connect()
            logger.info("Connected to database")
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise

    async def disconnect(self):
        """Disconnect from database"""
        try:
            await self.db.disconnect()
            logger.info("Disconnected from database")
        except Exception as e:
            logger.error(f"Error disconnecting from database: {e}")
            raise

    @contextlib.asynccontextmanager
    async def get_connection(self):
        """Context manager for database connection"""
        try:
            await self.connect()
            yield self.db
        finally:
            await self.disconnect()

    # User operations
    async def create_user(self, telegram_id: int, username: str = None, first_name: str = None) -> Dict:
        """Create a new user"""
        try:
            async with self.get_connection() as db:
                user = await db.user.create(
                    data={
                        'telegramId': telegram_id,
                        'username': username,
                        'firstName': first_name,
                    }
                )
                return user.dict()
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            raise

    async def get_user(self, telegram_id: int) -> Optional[Dict]:
        """Get user by Telegram ID"""
        try:
            async with self.get_connection() as db:
                user = await db.user.find_unique(
                    where={'telegramId': telegram_id}
                )
                return user.dict() if user else None
        except Exception as e:
            logger.error(f"Error getting user: {e}")
            raise

    # Alert operations
    async def create_alert(self, user_id: str, symbol: str, price_threshold: float, condition: str) -> Dict:
        """Create a price alert"""
        try:
            async with self.get_connection() as db:
                alert = await db.alert.create(
                    data={
                        'userId': user_id,
                        'symbol': symbol.upper(),
                        'priceThreshold': price_threshold,
                        'condition': condition,
                    }
                )
                return alert.dict()
        except Exception as e:
            logger.error(f"Error creating alert: {e}")
            raise

    async def get_user_alerts(self, user_id: str) -> List[Dict]:
        """Get all alerts for a user"""
        try:
            async with self.get_connection() as db:
                alerts = await db.alert.find_many(
                    where={
                        'userId': user_id,
                        'isActive': True
                    }
                )
                return [alert.dict() for alert in alerts]
        except Exception as e:
            logger.error(f"Error getting user alerts: {e}")
            raise

    # Subscription operations
    async def create_subscription(self, user_id: str, symbol: str) -> Dict:
        """Create a new subscription"""
        try:
            async with self.get_connection() as db:
                subscription = await db.subscription.create(
                    data={
                        'userId': user_id,
                        'symbol': symbol.upper(),
                    }
                )
                return subscription.dict()
        except Exception as e:
            logger.error(f"Error creating subscription: {e}")
            raise

    async def get_user_subscriptions(self, user_id: str) -> List[Dict]:
        """Get all subscriptions for a user"""
        try:
            async with self.get_connection() as db:
                subscriptions = await db.subscription.find_many(
                    where={'userId': user_id}
                )
                return [sub.dict() for sub in subscriptions]
        except Exception as e:
            logger.error(f"Error getting user subscriptions: {e}")
            raise

    # Portfolio operations
    async def update_portfolio(self, user_id: str, symbol: str, quantity: float, average_price: float) -> Dict:
        """Update or create portfolio entry"""
        try:
            async with self.get_connection() as db:
                portfolio = await db.portfolio.upsert(
                    where={
                        'userId_symbol': {
                            'userId': user_id,
                            'symbol': symbol.upper()
                        }
                    },
                    data={
                        'create': {
                            'userId': user_id,
                            'symbol': symbol.upper(),
                            'quantity': quantity,
                            'averagePrice': average_price
                        },
                        'update': {
                            'quantity': quantity,
                            'averagePrice': average_price
                        }
                    }
                )
                return portfolio.dict()
        except Exception as e:
            logger.error(f"Error updating portfolio: {e}")
            raise

    async def get_user_portfolio(self, user_id: str) -> List[Dict]:
        """Get user's portfolio"""
        try:
            async with self.get_connection() as db:
                portfolio = await db.portfolio.find_many(
                    where={'userId': user_id}
                )
                return [entry.dict() for entry in portfolio]
        except Exception as e:
            logger.error(f"Error getting user portfolio: {e}")
            raise

# Create singleton instance
prisma_service = PrismaService() 