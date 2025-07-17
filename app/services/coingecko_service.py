from typing import Dict, Optional, List
import httpx
from loguru import logger
from datetime import datetime
import asyncio

from app.core.config import settings
from app.models.schemas import MarketData
from app.services.cache_service import CacheService

class CoinGeckoService:
    _instance: Optional['CoinGeckoService'] = None
    _initialized: bool = False
    BASE_URL = "https://api.coingecko.com/api/v3"
    RATE_LIMIT_DELAY = 1.5  # Delay between requests in seconds

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(CoinGeckoService, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self.api_key = settings.COINGECKO_API_KEY
            self.client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                timeout=30.0,
                headers={
                    "X-CoinGecko-API-Key": self.api_key
                } if self.api_key else {}
            )
            self.cache = CacheService()
            self.last_request_time = 0
            self._initialized = True
            # Common symbol to ID mappings
            self.symbol_mappings = {
                "btc": "bitcoin",
                "eth": "ethereum",
                "usdt": "tether",
                "bnb": "binancecoin",
                "xrp": "ripple",
                "ada": "cardano",
                "doge": "dogecoin",
                "sol": "solana",
                "dot": "polkadot",
                "ltc": "litecoin"
            }

    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()

    async def _get_coin_id(self, symbol: str) -> Optional[str]:
        """Convert trading symbol to CoinGecko coin ID with caching"""
        try:
            symbol = symbol.lower()
            
            # Check common mappings first
            if symbol in self.symbol_mappings:
                return self.symbol_mappings[symbol]
            
            # Check cache
            cache_key = f"coin_id_mapping:{symbol}"
            cached_id = await self.cache.get_key(cache_key)
            if cached_id:
                return cached_id
            
            # Search for the coin ID
            await self._wait_for_rate_limit()
            response = await self.client.get(
                "/search",
                params={"query": symbol}
            )
            response.raise_for_status()
            data = response.json()
            
            coins = data.get("coins", [])
            if not coins:
                return None
                
            # Find exact symbol match
            for coin in coins:
                if coin["symbol"].lower() == symbol:
                    coin_id = coin["id"]
                    # Cache the mapping for future use
                    await self.cache.set_key(cache_key, coin_id, expiry=86400)  # Cache for 24 hours
                    return coin_id
            
            return None

        except Exception as e:
            logger.error(f"Error getting coin ID for {symbol}: {e}")
            return None

    async def get_price(self, symbol: str) -> Optional[MarketData]:
        """Get current price and market data for a symbol"""
        try:
            # Get coin ID first
            coin_id = await self._get_coin_id(symbol)
            if not coin_id:
                return None
            
            await self._wait_for_rate_limit()
            
            response = await self.client.get(
                f"/simple/price",
                params={
                    "ids": coin_id,
                    "vs_currencies": "usd",
                    "include_market_cap": "true",
                    "include_24hr_vol": "true",
                    "include_24hr_change": "true",
                    "include_last_updated_at": "true"
                }
            )
            response.raise_for_status()
            data = response.json()

            if coin_id not in data:
                return None

            coin_data = data[coin_id]
            
            # Get additional market data
            details = await self.get_coin_details(coin_id)
            
            return MarketData(
                symbol=symbol.upper(),
                price=coin_data["usd"],
                price_change_24h=coin_data["usd_24h_change"],
                market_cap=coin_data["usd_market_cap"],
                volume_24h=coin_data["usd_24h_vol"],
                high_24h=details.get("high_24h", 0.0),
                low_24h=details.get("low_24h", 0.0),
                last_updated=datetime.fromtimestamp(coin_data["last_updated_at"])
            )

        except Exception as e:
            logger.error(f"Error fetching price for {symbol}: {e}")
            return None

    async def get_coin_details(self, coin_id: str) -> Dict:
        """Get detailed coin information"""
        try:
            response = await self.client.get(
                f"/coins/{coin_id}",
                params={
                    "localization": "false",
                    "tickers": "false",
                    "community_data": "false",
                    "developer_data": "false"
                }
            )
            response.raise_for_status()
            data = response.json()

            market_data = data.get("market_data", {})
            return {
                "high_24h": market_data.get("high_24h", {}).get("usd", 0.0),
                "low_24h": market_data.get("low_24h", {}).get("usd", 0.0)
            }

        except Exception as e:
            logger.error(f"Error fetching coin details for {coin_id}: {e}")
            return {}

    async def get_trending_coins(self) -> List[Dict]:
        """Get list of trending coins with details"""
        try:
            await self._wait_for_rate_limit()
            
            response = await self.client.get("/search/trending")
            response.raise_for_status()
            data = response.json()

            result = []
            btc_price = await self._get_btc_price()  # Get BTC price once for all conversions
            
            for coin in data.get("coins", [])[:10]:
                try:
                    item = coin["item"]
                    coin_id = item["id"]
                    
                    # Get cached price data if available
                    cache_key = f"coin_price_{coin_id}"
                    cached_data = await self.cache.get_key(cache_key)
                    
                    if not cached_data:
                        await self._wait_for_rate_limit()
                        # Fetch current price data
                        price_response = await self.client.get(
                            "/simple/price",
                            params={
                                "ids": coin_id,
                                "vs_currencies": "usd",
                                "include_24h_vol": "true",
                                "include_24h_change": "true",
                                "include_market_cap": "true"
                            }
                        )
                        price_response.raise_for_status()
                        price_data = price_response.json().get(coin_id, {})
                        
                        # Cache the price data for 1 minute
                        await self.cache.set_key(cache_key, price_data, expiry=60)
                    else:
                        price_data = cached_data

                    result.append({
                        "id": coin_id,
                        "symbol": item["symbol"].upper(),
                        "name": item["name"],
                        "market_cap_rank": item.get("market_cap_rank"),
                        "price": price_data.get("usd", item.get("price_btc", 0) * btc_price),
                        "price_change_24h": price_data.get("usd_24h_change", 0),
                        "volume_24h": price_data.get("usd_24h_vol", 0),
                        "market_cap": price_data.get("usd_market_cap", 0),
                        "thumb": item.get("thumb"),
                        "score": item.get("score", 0)
                    })
                except Exception as e:
                    logger.error(f"Error processing trending coin {coin_id}: {e}")
                    continue

            # Sort by market cap rank if available, otherwise by score
            result.sort(key=lambda x: (
                x["market_cap_rank"] if x["market_cap_rank"] is not None else float('inf'),
                -x.get("score", 0)
            ))

            return result[:10]  # Ensure we return at most 10 coins

        except Exception as e:
            logger.error(f"Error fetching trending coins: {e}")
            return []

    async def _wait_for_rate_limit(self):
        """Ensure we respect rate limits by waiting between requests"""
        current_time = datetime.now().timestamp()
        time_since_last_request = current_time - self.last_request_time
        
        if time_since_last_request < self.RATE_LIMIT_DELAY:
            await asyncio.sleep(self.RATE_LIMIT_DELAY - time_since_last_request)
        
        self.last_request_time = datetime.now().timestamp()

    async def _get_btc_price(self) -> float:
        """Get current BTC price in USD with caching"""
        try:
            # Try to get from cache first
            btc_price = await self.cache.get_key("btc_price_usd")
            if btc_price:
                return float(btc_price)

            await self._wait_for_rate_limit()

            # If not in cache, fetch from API
            response = await self.client.get(
                "/simple/price",
                params={
                    "ids": "bitcoin",
                    "vs_currencies": "usd"
                }
            )
            response.raise_for_status()
            data = response.json()
            
            price = float(data["bitcoin"]["usd"])
            
            # Cache the price for 1 minute
            await self.cache.set_key("btc_price_usd", str(price), expiry=60)
            
            return price

        except Exception as e:
            logger.error(f"Error fetching BTC price: {e}")
            return 0.0

    async def get_supported_coins(self) -> List[Dict]:
        """Get list of supported coins"""
        try:
            response = await self.client.get("/coins/list")
            response.raise_for_status()
            return response.json()

        except Exception as e:
            logger.error(f"Error fetching supported coins: {e}")
            return []

# Create singleton instance
coingecko_service = CoinGeckoService() 