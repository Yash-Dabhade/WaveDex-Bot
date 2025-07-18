from typing import List, Dict, Optional, Any
from loguru import logger
import asyncio
from datetime import datetime, timezone
import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Set, Tuple, List, Dict, Optional, Any

from app.core.db import db
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
        """Monitor active alerts and trigger notifications with optimized price fetching"""
        while self._running:
            try:
                # Get all active alerts
                alerts = await self._get_active_alerts()
                if not alerts:
                    await asyncio.sleep(self.ALERT_CHECK_INTERVAL)
                    continue
                
                # Group alerts by symbol and collect unique symbols
                symbol_alerts: Dict[str, List[Alert]] = {}
                for alert in alerts:
                    symbol = alert.symbol.upper()
                    if symbol not in symbol_alerts:
                        symbol_alerts[symbol] = []
                    symbol_alerts[symbol].append(alert)
                
                # Fetch prices for all unique symbols concurrently
                symbols = list(symbol_alerts.keys())
                prices = await self._fetch_prices_concurrently(symbols)
                
                # Process alerts for each symbol with its price
                tasks = []
                for symbol, symbol_alerts_list in symbol_alerts.items():
                    price_data = prices.get(symbol)
                    if price_data:
                        for alert in symbol_alerts_list:
                            tasks.append(self._process_alert(alert, price_data))
                
                # Run alert processing concurrently
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                
                await asyncio.sleep(self.ALERT_CHECK_INTERVAL)
                
            except Exception as e:
                logger.error(f"Error in alert monitoring: {e}")
                await asyncio.sleep(min(5, self.ALERT_CHECK_INTERVAL))  # Shorter delay on error

    async def _get_active_alerts(self) -> List[Alert]:
        """Get all active alerts from database"""
        try:
            alerts = await db.prisma.alert.find_many(
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
        """Legacy method - kept for backward compatibility"""
        try:
            prices = await self._fetch_prices_concurrently([symbol])
            if symbol in prices:
                price_data = prices[symbol]
                for alert in alerts:
                    await self._process_alert(alert, price_data)
        except Exception as e:
            logger.error(f"Error checking alerts for {symbol}: {e}")

    async def _fetch_prices_concurrently(self, symbols: List[str]) -> Dict[str, MarketData]:
        """Fetch prices for multiple symbols concurrently with caching"""
        if not symbols:
            return {}
            
        # Check cache first
        cache_keys = [f"price:{symbol.lower()}" for symbol in symbols]
        cached_results = await asyncio.gather(
            *[self.cache.get_key(key) for key in cache_keys],
            return_exceptions=True
        )
        
        # Process cached results
        results = {}
        remaining_symbols = []
        
        for symbol, cached in zip(symbols, cached_results):
            if isinstance(cached, dict) and not isinstance(cached, Exception):
                results[symbol] = MarketData(**cached)
            else:
                remaining_symbols.append(symbol)
        
        # If we have all prices from cache, return them
        if not remaining_symbols:
            return results
            
        # Fetch remaining prices in parallel
        tasks = []
        for symbol in remaining_symbols:
            tasks.append(self._fetch_and_cache_price(symbol))
        
        # Run all price fetches concurrently
        fetched_prices = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process fetched prices
        for symbol, result in zip(remaining_symbols, fetched_prices):
            if isinstance(result, MarketData) and not isinstance(result, Exception):
                results[symbol] = result
        
        return results
    
    async def _fetch_and_cache_price(self, symbol: str) -> Optional[MarketData]:
        """Fetch price for a single symbol and cache the result"""
        try:
            market_data = await coingecko_service.get_price(symbol)
            if market_data:
                cache_key = f"price:{symbol.lower()}"
                await self.cache.set_key(
                    cache_key,
                    market_data.dict(),
                    expiry=self.PRICE_CACHE_TTL
                )
                return market_data
        except Exception as e:
            logger.error(f"Error fetching price for {symbol}: {e}")
        return None
        
    async def _process_alert(self, alert: Alert, price_data: MarketData) -> None:
        """Process a single alert with the given price data"""
        try:
            current_price = price_data.price
            triggered = (
                (alert.condition == AlertCondition.ABOVE and current_price >= alert.price_threshold) or
                (alert.condition == AlertCondition.BELOW and current_price <= alert.price_threshold)
            )
            
            if triggered:
                await self._trigger_alert(alert, price_data)
        except Exception as e:
            logger.error(f"Error processing alert {alert.id}: {e}")

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
            async with db.session() as session:
                await db.prisma.alert.update(
                    where={"id": alert.id},
                    data={"isActive": False}
                )

            logger.info(f"Alert triggered for {alert.symbol}")

        except Exception as e:
            logger.error(f"Error triggering alert: {e}")

    async def create_alert(self, user_id: str, symbol: str, price: float, condition: str) -> Alert:
        """Create a new price alert"""
        try:
            alert = await db.prisma.alert.create(
                data={
                    "userId": user_id,
                    "symbol": symbol.upper(),
                    "priceThreshold": price,
                    "condition": condition,
                    "isActive": True,
                    "createdAt": datetime.now(timezone.utc),
                    "updatedAt": datetime.now(timezone.utc)
                }
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
            symbol = alert.get("symbol", "").upper()
            if not symbol:
                logger.error(f"Invalid alert data: missing symbol")
                return False
                
            # Get current price data
            price_data = await price_service.get_price(symbol)
            if not price_data or "error" in price_data:
                logger.error(f"Failed to get price for {symbol}: {price_data.get('error', 'Unknown error')}")
                return False

            # Get the current price from the price data
            current_price = price_data.get("price_usd")
            if current_price is None:
                logger.error(f"No price data available for {symbol}")
                return False

            target_price = alert.get("target_price")
            condition = alert.get("condition", "").lower()
            
            if target_price is None:
                logger.error(f"Invalid alert data: missing target_price")
                return False
                
            if condition not in ["above", "below"]:
                logger.error(f"Invalid alert condition: {condition}")
                return False

            # Update alert with latest price data
            alert["current_price"] = current_price
            alert["price_data"] = price_data
            
            # Convert to float for comparison
            try:
                current_price_float = float(current_price)
                target_price_float = float(target_price)
                
                logger.info(f"Checking alert for {symbol}: {current_price_float} {condition.upper()} {target_price_float}")
                
                if condition == "above":
                    return current_price_float >= target_price_float
                else:  # condition == "below"
                    return current_price_float <= target_price_float
                    
            except (ValueError, TypeError) as e:
                logger.error(f"Error comparing prices: {e}")
                return False

        except Exception as e:
            logger.error(f"Error checking alert {alert.get('id')}: {e}")
            return False

    async def set_alert(self, user_id: int, symbol: str, target_price: float, condition: str) -> Dict[str, Any]:
        """Set a price alert for a user"""
        logger.info(f"[set_alert] Starting alert creation for user {user_id}, symbol {symbol}, target {target_price}, condition {condition}")
        
        try:
            # Validate inputs
            if not symbol or not isinstance(symbol, str):
                error_msg = f"Invalid symbol: {symbol}"
                logger.error(f"[set_alert] {error_msg}")
                return {"error": "❌ Invalid symbol. Please provide a valid cryptocurrency symbol."}
            
            symbol = symbol.upper()
            logger.info(f"[set_alert] Validated symbol: {symbol}")
            
            try:
                target_price = float(target_price)
                if target_price <= 0:
                    error_msg = f"Target price must be positive, got {target_price}"
                    logger.error(f"[set_alert] {error_msg}")
                    return {"error": "❌ Target price must be greater than 0"}
                logger.info(f"[set_alert] Validated target price: {target_price}")
            except (ValueError, TypeError) as e:
                error_msg = f"Invalid target price: {target_price}, error: {str(e)}"
                logger.error(f"[set_alert] {error_msg}")
                return {"error": "❌ Invalid target price. Please provide a valid number."}
            
            condition = condition.lower()
            if condition not in ["above", "below"]:
                error_msg = f"Invalid condition: {condition}"
                logger.error(f"[set_alert] {error_msg}")
                return {"error": "❌ Invalid condition. Must be 'above' or 'below'"}
            
            logger.info(f"[set_alert] Validated condition: {condition}")

            # Get current price data
            logger.info(f"[set_alert] Fetching price for {symbol}...")
            price_data = await price_service.get_price(symbol)
            logger.info(f"[set_alert] Price data received: {price_data}")
            
            # Check for error in price data
            if not price_data:
                error_msg = "No price data received from price service"
                logger.error(f"[set_alert] {error_msg}")
                return {"error": "❌ Failed to fetch price data. Please try again later."}
                
            if isinstance(price_data, dict) and "error" in price_data:
                error_msg = price_data.get("error", "Unknown error from price service")
                logger.error(f"[set_alert] Price service error: {error_msg}")
                return {"error": f"❌ {error_msg}. Please check the symbol and try again."}

            # Get the current price from the price data
            current_price = price_data.get("price_usd")
            logger.info(f"[set_alert] Extracted price: {current_price}")
            
            if current_price is None:
                error_msg = f"No price data in response for {symbol}"
                logger.error(f"[set_alert] {error_msg}")
                return {"error": "❌ Could not determine current price for the symbol. Please try again."}

            # Check for duplicate alert
            user_alerts_key = f"{self._user_alerts_key_prefix}{user_id}"
            logger.info(f"[set_alert] Checking for duplicate alerts with key: {user_alerts_key}")
            
            try:
                alert_ids = await self.cache.smembers(user_alerts_key)
                logger.info(f"[set_alert] Found {len(alert_ids)} existing alerts")
                
                for alert_id in alert_ids:
                    alert_key = f"{self._alert_key_prefix}{alert_id}"
                    existing_alert = await self.cache.get_key(alert_key)
                    if existing_alert:
                        existing_symbol = existing_alert.get("symbol", "").upper()
                        existing_target = existing_alert.get("target_price")
                        existing_condition = existing_alert.get("condition", "").lower()
                        
                        if (existing_symbol == symbol and 
                            existing_target == target_price and 
                            existing_condition == condition):
                            error_msg = f"Duplicate alert found for {symbol} {condition} {target_price}"
                            logger.warning(f"[set_alert] {error_msg}")
                            return {"error": f"❌ You already have a similar alert for {symbol}"}
            except Exception as e:
                logger.error(f"[set_alert] Error checking for duplicate alerts: {e}")
                # Continue with alert creation even if duplicate check fails

            # Create alert data
            alert_id = f"{int(time.time())}_{user_id}_{symbol}"
            alert_data = {
                "id": alert_id,
                "user_id": user_id,
                "symbol": symbol,
                "target_price": target_price,
                "condition": condition,
                "current_price": current_price,
                "created_at": int(time.time()),
                "price_data": price_data
            }
            logger.info(f"[set_alert] Created alert data: {alert_data}")

            # Save alert in cache
            alert_key = f"{self._alert_key_prefix}{alert_id}"
            logger.info(f"[set_alert] Saving alert with key: {alert_key}")
            
            try:
                # Store alert data and add to user's alert list
                await self.cache.set_key(alert_key, alert_data)
                await self.cache.sadd(user_alerts_key, alert_id)
                logger.info("[set_alert] Alert saved successfully")
                
                # Format the response message
                formatted_target = "${:,.2f}".format(target_price)
                formatted_price = "${:,.2f}".format(current_price)
                change_24h = price_data.get("change_24h", 0)
                change_emoji = "📈" if change_24h >= 0 else "📉"
                
                success_msg = (
                    f"✅ *Alert Set Successfully* ✅\n\n"
                    f"• *Symbol:* {symbol}\n"
                    f"• *Condition:* Price {condition.upper()} {formatted_target}\n"
                    f"• *Current Price:* {formatted_price}\n"
                    f"• *24h Change:* {change_emoji} {abs(change_24h):.2f}%"
                )
                
                logger.info(f"[set_alert] Success: {success_msg}")
                
                return {
                    "success": True,
                    "message": success_msg,
                    "alert_id": alert_id
                }
                
            except Exception as e:
                error_msg = f"Failed to save alert: {str(e)}"
                logger.error(f"[set_alert] {error_msg}")
                return {"error": "❌ Failed to save alert. Please try again."}


        except Exception as e:
            logger.error(f"Error in set_alert: {e}")
            return {"error": "❌ Failed to set alert. Please try again."}

# Create singleton instance
alert_service = AlertService() 