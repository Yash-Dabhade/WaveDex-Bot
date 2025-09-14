from typing import Dict, Optional, List
import httpx
from loguru import logger
from datetime import datetime
import asyncio

from env import env
from app.models.schemas import MarketData
from app.services.cache_service import CacheService

class StockPriceService:
    _instance: Optional['StockPriceService'] = None
    _initialized: bool = False
    BASE_URL = "https://finnhub.io/api/v1"
    RATE_LIMIT_DELAY = 1.0  # Delay between requests in seconds

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(StockPriceService, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self.api_key = env.FINNHUB_API_KEY
            self.client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                timeout=30.0,
                headers={"X-Finnhub-Token": self.api_key}
            )
            self.cache = CacheService()
            self.last_request_time = 0
            self._initialized = True

    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()

    async def get_price(self, symbol: str) -> Optional[MarketData]:
        """Get current stock price and basic market data"""
        try:
            symbol = symbol.upper()
            cache_key = f"stock_price_{symbol}"

            # Try cache first
            cached = await self.cache.get_key(cache_key)
            if cached:
                return MarketData.parse_raw(cached)

            await self._wait_for_rate_limit()

            # Get quote
            quote_response = await self.client.get("/quote", params={"symbol": symbol})
            quote_response.raise_for_status()
            quote = quote_response.json()

            if not quote or "c" not in quote:
                logger.warning(f"No data returned for stock symbol {symbol}")
                return None

            # Get company profile for additional info
            profile_response = await self.client.get("/stock/profile2", params={"symbol": symbol})
            profile_response.raise_for_status()
            profile = profile_response.json()

            market_data = MarketData(
                symbol=symbol,
                price=quote["c"],
                price_change_24h=(quote["c"] - quote["pc"]) * 100 / quote["pc"] if quote["pc"] != 0 else 0.0,
                market_cap=profile.get("marketCapitalization", 0) * 1_000_000,  # Convert from millions
                volume_24h=quote.get("v", 0),
                high_24h=quote.get("h", 0.0),
                low_24h=quote.get("l", 0.0),
                last_updated=datetime.fromtimestamp(quote.get("t", 0))
            )

            # Cache result for 60 seconds
            await self.cache.set_key(cache_key, market_data.json(), expiry=60)

            return market_data

        except Exception as e:
            logger.error(f"Error fetching stock price for {symbol}: {e}")
            return None

    async def get_trending_stocks(self) -> List[Dict]:
        """Fetch trending stocks (mocked or via external API)"""
        try:
            # Finnhub doesn't have a direct trending endpoint; simulate with popular tickers
            trending_symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "META", "NVDA", "NFLX", "DIS", "V"]

            result = []
            for symbol in trending_symbols:
                market_data = await self.get_price(symbol)
                if market_data:
                    result.append({
                        "symbol": market_data.symbol,
                        "price": market_data.price,
                        "change_percent": market_data.price_change_24h,
                        "volume": market_data.volume_24h,
                        "high_24h": market_data.high_24h,
                        "low_24h": market_data.low_24h,
                        "last_updated": market_data.last_updated.isoformat()
                    })

            return result

        except Exception as e:
            logger.error(f"Error fetching trending stocks: {e}")
            return []

    async def _wait_for_rate_limit(self):
        """Respect rate limits by waiting between requests"""
        current_time = datetime.now().timestamp()
        time_since_last_request = current_time - self.last_request_time

        if time_since_last_request < self.RATE_LIMIT_DELAY:
            await asyncio.sleep(self.RATE_LIMIT_DELAY - time_since_last_request)

        self.last_request_time = datetime.now().timestamp()

# Singleton instance
stock_price_service = StockPriceService()