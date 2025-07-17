from typing import Dict, Optional, List
import httpx
from loguru import logger
from datetime import datetime

from app.core.config import settings
from app.services.cache_service import CacheService

class CoinMarketCapService:
    _instance: Optional['CoinMarketCapService'] = None
    _initialized: bool = False
    BASE_URL = "https://pro-api.coinmarketcap.com/v1"

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(CoinMarketCapService, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self.api_key = settings.COINMARKETCAP_API_KEY
            self.client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                timeout=30.0,
                headers={
                    "X-CMC_PRO_API_KEY": self.api_key,
                    "Accept": "application/json"
                }
            )
            self.cache = CacheService()
            self._initialized = True

    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()

    async def get_trending_coins(self, limit: int = 100) -> List[Dict]:
        """Get top trending coins sorted by 24h percent change"""
        try:
            # Try to get from cache first
            cache_key = f"cmc_trending:{limit}"
            cached_data = await self.cache.get_key(cache_key)
            if cached_data:
                return cached_data

            # Fetch from API using the listings endpoint
            response = await self.client.get(
                "/cryptocurrency/listings/latest",
                params={
                    "start": 1,
                    "limit": limit,  # Get more coins to find significant movers
                    "convert": "USD",
                    "sort": "volume_24h",  # Sort by volume to get actively traded coins
                    "sort_dir": "desc"
                }
            )
            response.raise_for_status()
            data = response.json()

            if "data" not in data:
                return []

            # Process and format the data
            result = []
            for coin in data["data"]:
                usd_quote = coin["quote"]["USD"]
                # Only include coins with significant volume
                if usd_quote["volume_24h"] > 100000:  # Filter out low volume coins
                    result.append({
                        "id": coin["id"],
                        "symbol": coin["symbol"],
                        "name": coin["name"],
                        "price": usd_quote["price"],
                        "market_cap": usd_quote["market_cap"],
                        "volume_24h": usd_quote["volume_24h"],
                        "percent_change_24h": usd_quote["percent_change_24h"],
                        "percent_change_1h": usd_quote["percent_change_1h"],
                        "percent_change_7d": usd_quote["percent_change_7d"],
                        "market_cap_rank": coin["cmc_rank"],
                        "last_updated": datetime.strptime(
                            usd_quote["last_updated"],
                            "%Y-%m-%dT%H:%M:%S.%fZ"
                        ).timestamp()
                    })

            # Sort by absolute percent change to get biggest movers
            result.sort(key=lambda x: abs(x["percent_change_24h"]), reverse=True)
            result = result[:10]  # Keep top 10 movers

            # Cache for 10 minutes
            await self.cache.set_key(cache_key, result, expiry=600)
            return result

        except Exception as e:
            logger.error(f"Error fetching trending coins from CMC: {e}")
            return []

# Create singleton instance
coinmarketcap_service = CoinMarketCapService()