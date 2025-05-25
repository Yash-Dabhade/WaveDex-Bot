from typing import Dict, Optional, List
import httpx
from loguru import logger
from datetime import datetime

from app.core.config import settings
from app.models.schemas import MarketData

class CoinGeckoService:
    _instance: Optional['CoinGeckoService'] = None
    _initialized: bool = False
    BASE_URL = "https://api.coingecko.com/api/v3"

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
            self._initialized = True

    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()

    async def get_price(self, symbol: str) -> Optional[MarketData]:
        """Get current price and market data for a symbol"""
        try:
            # Convert symbol to CoinGecko ID format
            coin_id = symbol.lower()
            
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

    async def get_trending_coins(self) -> List[str]:
        """Get list of trending coins"""
        try:
            response = await self.client.get("/search/trending")
            response.raise_for_status()
            data = response.json()

            return [
                coin["item"]["symbol"].upper()
                for coin in data.get("coins", [])[:10]
            ]

        except Exception as e:
            logger.error(f"Error fetching trending coins: {e}")
            return []

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