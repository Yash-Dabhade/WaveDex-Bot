from typing import List, Dict, Optional, Any
from loguru import logger
import asyncio
from datetime import datetime
import json
import time

from app.services.prisma_service import prisma_service
from app.services.coingecko_service import coingecko_service
from app.services.cache_service import CacheService
from app.models.schemas import Alert, AlertCondition, MarketData
from app.services.price_service import price_service
from app.services.notification_service import notification_service

class AlertService:
    _instance: Optional['AlertService'] = None
    _initialized: bool = False
    ALERT_CHECK_INTERVAL = 60  # Check every minute
    PRICE_CACHE_TTL = 60  # Cache prices for 1 minute

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AlertService, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self.cache = CacheService()
            self._initialized = True
            self._running = False
            self._task: Optional[asyncio.Task] = None
            self._alert_key_prefix = "crypto_alert:"
            self._user_alerts_key_prefix = "user_alerts:"

    async def start_monitoring(self):
        """Start the alert monitoring loop"""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._monitor_alerts())
        logger.info("Alert monitoring started")

    async def stop_monitoring(self):
        """Stop the alert monitoring loop"""
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Alert monitoring stopped")

    async def _monitor_alerts(self):
        """Monitor active alerts and trigger notifications"""
        while self._running:
            try:
                # Get all active alerts
                alerts = await self._get_active_alerts()
                
                # Group alerts by symbol to minimize API calls
                symbol_alerts: Dict[str, List[Alert]] = {}
                for alert in alerts:
                    if alert.symbol not in symbol_alerts:
                        symbol_alerts[alert.symbol] = []
                    symbol_alerts[alert.symbol].append(alert)

                # Check each symbol's price
                for symbol, alerts in symbol_alerts.items():
                    await self._check_symbol_alerts(symbol, alerts)

                await asyncio.sleep(self.ALERT_CHECK_INTERVAL)

            except Exception as e:
                logger.error(f"Error in alert monitoring: {e}")
                await asyncio.sleep(self.ALERT_CHECK_INTERVAL)

    async def _get_active_alerts(self) -> List[Alert]:
        """Get all active alerts from database"""
        try:
            async with prisma_service.get_connection() as db:
                alerts = await db.alert.find_many(
                    where={"isActive": True},
                    include={
                        "user": True
                    }
                )
                return [Alert.from_orm(alert) for alert in alerts]
        except Exception as e:
            logger.error(f"Error fetching active alerts: {e}")
            return []

    async def _check_symbol_alerts(self, symbol: str, alerts: List[Alert]):
        """Check alerts for a specific symbol"""
        try:
            # Get current price
            market_data = await self._get_market_data(symbol)
            if not market_data:
                return

            current_price = market_data.price

            # Check each alert
            for alert in alerts:
                triggered = (
                    (alert.condition == AlertCondition.ABOVE and current_price >= alert.price_threshold) or
                    (alert.condition == AlertCondition.BELOW and current_price <= alert.price_threshold)
                )

                if triggered:
                    await self._trigger_alert(alert, market_data)

        except Exception as e:
            logger.error(f"Error checking alerts for {symbol}: {e}")

    async def _get_market_data(self, symbol: str) -> Optional[MarketData]:
        """Get market data with caching"""
        cache_key = f"price:{symbol.lower()}"

        # Try to get from cache
        cached_data = await self.cache.get_key(cache_key)
        if cached_data:
            return MarketData(**cached_data)

        # Fetch from API
        market_data = await coingecko_service.get_price(symbol)
        if market_data:
            # Cache the result
            await self.cache.set_key(
                cache_key,
                market_data.dict(),
                expiry=self.PRICE_CACHE_TTL
            )

        return market_data

    async def _trigger_alert(self, alert: Alert, market_data: MarketData):
        """Trigger alert notification and update alert status"""
        try:
            # Format message
            message = (
                f"🚨 Price Alert for {alert.symbol}!\n\n"
                f"Current Price: ${market_data.price:,.2f}\n"
                f"Alert {alert.condition}: ${alert.price_threshold:,.2f}\n"
                f"24h Change: {market_data.price_change_24h:+.2f}%\n\n"
                f"Market Cap: ${market_data.market_cap:,.0f}\n"
                f"24h Volume: ${market_data.volume_24h:,.0f}"
            )

            # Send notification
            await notification_service.send_message(
                chat_id=alert.user.telegramId,
                text=message
            )

            # Deactivate alert
            async with prisma_service.get_connection() as db:
                await db.alert.update(
                    where={"id": alert.id},
                    data={"isActive": False}
                )

            logger.info(f"Alert triggered for {alert.symbol}")

        except Exception as e:
            logger.error(f"Error triggering alert: {e}")

    async def create_alert(self, user_id: str, symbol: str, price: float, condition: str) -> Alert:
        """Create a new price alert"""
        try:
            alert = await prisma_service.create_alert(
                user_id=user_id,
                symbol=symbol,
                price_threshold=price,
                condition=condition
            )
            return Alert.from_orm(alert)
        except Exception as e:
            logger.error(f"Error creating alert: {e}")
            raise

    async def get_user_alerts(self, user_id: int) -> List[Dict[str, Any]]:
        """Get all active alerts for a user"""
        try:
            user_alerts_key = f"{self._user_alerts_key_prefix}{user_id}"
            alert_ids = await self.cache.smembers(user_alerts_key)

            alerts = []
            for alert_id in alert_ids:
                alert_key = f"{self._alert_key_prefix}{alert_id}"
                alert_data = await self.cache.get_key(alert_key)
                
                if alert_data:
                    alert = alert_data
                    # Get current price
                    price_data = await price_service.get_price(alert["symbol"])
                    if "error" not in price_data:
                        alert["current_price"] = price_data["price_usd"]
                    alerts.append(alert)

            return sorted(alerts, key=lambda x: x["created_at"], reverse=True)

        except Exception as e:
            logger.error(f"Error getting user alerts: {e}")
            return []

    async def delete_alert(self, user_id: int, alert_id: str) -> Dict[str, Any]:
        """Delete a specific alert"""
        try:
            alert_key = f"{self._alert_key_prefix}{alert_id}"
            user_alerts_key = f"{self._user_alerts_key_prefix}{user_id}"

            # Check if alert exists and belongs to user
            alert = await self.cache.get_key(alert_key)
            if not alert:
                return {"error": "Alert not found"}
            if alert["user_id"] != user_id:
                return {"error": "Alert not found"}

            # Delete alert
            await self.cache.delete_key(alert_key)
            await self.cache.srem(user_alerts_key, alert_id)

            return {
                "success": True,
                "message": f"✅ Alert for {alert['symbol']} deleted successfully"
            }

        except Exception as e:
            logger.error(f"Error deleting alert: {e}")
            return {"error": "Failed to delete alert"}

    async def check_alerts(self) -> List[Dict[str, Any]]:
        """Check all alerts against current prices and return triggered alerts"""
        try:
            triggered_alerts = []
            # Get all user alert keys
            user_keys = await self.cache.scan_keys(f"{self._user_alerts_key_prefix}*")
            
            for user_key in user_keys:
                alert_ids = await self.cache.smembers(user_key)
                user_id = int(user_key.split(":")[-1])
                
                for alert_id in alert_ids:
                    alert_key = f"{self._alert_key_prefix}{alert_id}"
                    alert_data = await self.cache.get_key(alert_key)
                    
                    if alert_data:
                        alert = alert_data
                        if await self._check_alert(alert):
                            triggered_alerts.append(alert)
                            # Delete triggered alert
                            await self.delete_alert(user_id, alert_id)

            return triggered_alerts

        except Exception as e:
            logger.error(f"Error checking alerts: {e}")
            return []

    async def _check_alert(self, alert: Dict[str, Any]) -> bool:
        """Check if an alert should be triggered"""
        try:
            price_data = await price_service.get_price(alert["symbol"])
            if "error" in price_data:
                return False

            current_price = price_data["price_usd"]
            target_price = alert["target_price"]
            condition = alert["condition"]

            alert["current_price"] = current_price
            alert["price_data"] = price_data

            return (
                (condition == "above" and current_price >= target_price) or
                (condition == "below" and current_price <= target_price)
            )

        except Exception as e:
            logger.error(f"Error checking alert {alert['id']}: {e}")
            return False

    async def set_alert(self, user_id: int, symbol: str, target_price: float, condition: str) -> Dict[str, Any]:
        """Set a price alert for a user"""
        try:
            # Validate the symbol
            price_data = await price_service.get_price(symbol)
            if "error" in price_data:
                return {"error": price_data["error"]}

            # Validate condition
            if condition not in ["above", "below"]:
                return {"error": "Condition must be 'above' or 'below'"}

            # Create alert data
            alert_id = f"{int(time.time())}_{user_id}_{symbol}"
            alert_data = {
                "id": alert_id,
                "user_id": user_id,
                "symbol": symbol.upper(),
                "target_price": target_price,
                "condition": condition,
                "current_price": price_data["price_usd"],
                "created_at": int(time.time())
            }

            # Save alert in cache
            alert_key = f"{self._alert_key_prefix}{alert_id}"
            user_alerts_key = f"{self._user_alerts_key_prefix}{user_id}"

            # Store alert data and add to user's alert list
            await self.cache.set_key(alert_key, alert_data)
            await self.cache.sadd(user_alerts_key, alert_id)

            return {
                "success": True,
                "message": (
                    f"✅ Alert set for {symbol.upper()}\n"
                    f"Target: ${target_price:,.2f} ({condition})\n"
                    f"Current price: ${price_data['price_usd']:,.2f}"
                ),
                "alert_id": alert_id
            }

        except Exception as e:
            logger.error(f"Error setting alert: {e}")
            return {"error": "Failed to set alert"}

# Create singleton instance
alert_service = AlertService() 