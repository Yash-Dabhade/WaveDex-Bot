from prisma import Prisma
from typing import Optional, Any, Dict, List
from loguru import logger
import asyncio
from datetime import datetime

class PrismaService:
    _instance = None
    _lock = asyncio.Lock()
    _initialized = False
    
    def __new__(cls):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def initialize(self):
        """Initialize the service with connection pool"""
        if self._initialized:
            return
            
        async with self._lock:
            if not self._initialized:  # Double check under lock
                try:
                    self.db = Prisma()
                    await self.db.connect()
                    logger.info("Database connection pool initialized")
                    self._initialized = True
                except Exception as e:
                    logger.error(f"Failed to initialize database connection: {e}")
                    raise

    async def shutdown(self):
        """Shutdown the service and close connections"""
        if self._initialized:
            async with self._lock:
                if self._initialized:
                    try:
                        await self.db.disconnect()
                        logger.info("Database connections closed")
                        self._initialized = False
                    except Exception as e:
                        logger.error(f"Error closing database connections: {e}")
                        raise

    async def _ensure_initialized(self):
        """Ensure service is initialized before operations"""
        if not self._initialized:
            await self.initialize()

    async def ensure_user_exists(self, user_id: str) -> None:
        """Ensure user exists in database and return the user"""
        await self._ensure_initialized()
        try:
            # Convert string user_id to integer for telegramId
            telegram_id = int(user_id)
            user = await self.db.user.find_unique(
                where={
                    "telegramId": telegram_id
                }
            )
            if not user:
                user = await self.db.user.create(
                    data={
                        "telegramId": telegram_id
                    }
                )
            return user
        except Exception as e:
            logger.error(f"Error ensuring user exists: {e}")
            raise

    async def get_user_portfolio(self, user_id: str) -> List[Dict]:
        """Get user's portfolio"""
        await self._ensure_initialized()
        try:
            # Get or create user to get database ID
            user = await self.ensure_user_exists(user_id)
            
            portfolio = await self.db.portfolio.find_many(
                where={
                    "userId": user.id  # Use id field from User model
                }
            )
            return [p.dict() for p in portfolio]
        except Exception as e:
            logger.error(f"Error getting user portfolio: {e}")
            raise

    async def update_portfolio(
        self,
        user_id: str,
        symbol: str,
        quantity: float,
        average_price: float
    ) -> Dict:
        """Update or create portfolio position"""
        await self._ensure_initialized()
        try:
            # Get or create user to get database ID
            user = await self.ensure_user_exists(user_id)
            
            result = await self.db.portfolio.upsert(
                where={
                    "userId_symbol": {
                        "userId": user.id,
                        "symbol": symbol
                    }
                },
                data={
                    "create": {
                        "user": {
                            "connect": {
                                "id": user.id
                            }
                        },
                        "symbol": symbol,
                        "quantity": quantity,
                        "averagePrice": average_price
                    },
                    "update": {
                        "quantity": quantity,
                        "averagePrice": average_price
                    }
                }
            )
            return result.dict()
        except Exception as e:
            logger.error(f"Error updating portfolio: {e}")
            raise

    async def delete_portfolio(self, user_id: str, symbol: str) -> None:
        """Delete portfolio position"""
        await self._ensure_initialized()
        try:
            # Get or create user to get database ID
            user = await self.ensure_user_exists(user_id)
            
            await self.db.portfolio.delete(
                where={
                    "userId_symbol": {
                        "userId": user.id,  # Use id field from User model
                        "symbol": symbol
                    }
                }
            )
        except Exception as e:
            logger.error(f"Error deleting portfolio position: {e}")
            raise

    # Alert operations
    async def create_alert(self, user_id: str, symbol: str, price_threshold: float, condition: str) -> Dict:
        """Create a price alert"""
        await self._ensure_initialized()
        try:
            # Get or create user to get database ID
            user = await self.ensure_user_exists(user_id)
            
            alert = await self.db.alert.create(
                data={
                    "user": {
                        "connect": {
                            "id": user.id
                        }
                    },
                    "symbol": symbol.upper(),
                    "priceThreshold": price_threshold,
                    "condition": condition
                }
            )
            return alert.dict()
        except Exception as e:
            logger.error(f"Error creating alert: {e}")
            raise

    async def get_user_alerts(self, user_id: str) -> List[Dict]:
        """Get all alerts for a user"""
        await self._ensure_initialized()
        try:
            # Get or create user to get database ID
            user = await self.ensure_user_exists(user_id)
            
            alerts = await self.db.alert.find_many(
                where={
                    'userId': user.id,  # Use id field from User model
                    'isActive': True
                }
            )
            return [alert.dict() for alert in alerts]
        except Exception as e:
            logger.error(f"Error getting user alerts: {e}")
            raise

    async def delete_alert(self, alert_id: str) -> None:
        """Delete an alert"""
        await self._ensure_initialized()
        try:
            await self.db.alert.delete(
                where={
                    'id': alert_id
                }
            )
        except Exception as e:
            logger.error(f"Error deleting alert: {e}")
            raise

    # User operations
    async def create_user(self, telegram_id: int, username: str = None, first_name: str = None) -> Dict:
        """Create a new user"""
        await self._ensure_initialized()
        try:
            user = await self.db.user.create(
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
        await self._ensure_initialized()
        try:
            user = await self.db.user.find_unique(
                where={'telegramId': telegram_id}
            )
            return user.dict() if user else None
        except Exception as e:
            logger.error(f"Error getting user: {e}")
            raise

    # Subscription operations
    async def create_subscription(self, user_id: str, symbol: str) -> Dict:
        """Create a new subscription"""
        await self._ensure_initialized()
        try:
            # Get or create user to get database ID
            user = await self.ensure_user_exists(user_id)
            
            subscription = await self.db.subscription.create(
                data={
                    "user": {
                        "connect": {
                            "id": user.id
                        }
                    },
                    "symbol": symbol.upper()
                }
            )
            return subscription.dict()
        except Exception as e:
            logger.error(f"Error creating subscription: {e}")
            raise

    async def get_user_subscriptions(self, user_id: str) -> List[Dict]:
        """Get all subscriptions for a user"""
        await self._ensure_initialized()
        try:
            # Get or create user to get database ID
            user = await self.ensure_user_exists(user_id)
            
            subscriptions = await self.db.subscription.find_many(
                where={'userId': user.id}  # Use id field from User model
            )
            return [sub.dict() for sub in subscriptions]
        except Exception as e:
            logger.error(f"Error getting user subscriptions: {e}")
            raise

# Create singleton instance
prisma_service = PrismaService() 