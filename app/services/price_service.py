from typing import Optional, Dict, Any, List
import aiohttp
from loguru import logger
from datetime import datetime, timedelta

from app.core.config import settings

class PriceService:
    def __init__(self):
        self.base_url = "https://api.coingecko.com/api/v3"
        self.session: Optional[aiohttp.ClientSession] = None

    async def initialize(self):
        """Initialize the HTTP session"""
        if not self.session:
            self.session = aiohttp.ClientSession()

    async def close(self):
        """Close the HTTP session"""
        if self.session:
            await self.session.close()
            self.session = None

    async def get_supported_coins(self) -> Dict[str, Any]:
        """Get list of supported cryptocurrencies"""
        try:
            if not self.session:
                await self.initialize()

            url = f"{self.base_url}/coins/list"
            async with self.session.get(url) as response:
                if response.status == 429:
                    return {"error": "Rate limit exceeded. Please try again later."}
                elif response.status != 200:
                    return {"error": "Failed to fetch supported coins"}

                data = await response.json()
                
                # Sort by symbol
                coins = sorted(data, key=lambda x: x['symbol'])
                return {
                    "coins": coins
                }

        except Exception as e:
            logger.error(f"Error fetching supported coins: {e}")
            return {"error": "Failed to fetch supported coins"}

    async def get_price_history(self, symbol: str, days: int = 7) -> Dict[str, Any]:
        """Get historical price data for a cryptocurrency"""
        try:
            if not self.session:
                await self.initialize()

            # Get coin ID first
            coin_id = await self._get_coin_id(symbol.lower())
            if not coin_id:
                return {"error": f"Cryptocurrency {symbol} not found"}

            # Fetch historical data
            url = f"{self.base_url}/coins/{coin_id}/market_chart"
            params = {
                "vs_currency": "usd",
                "days": str(days),
                "interval": "daily"
            }

            async with self.session.get(url, params=params) as response:
                if response.status == 429:
                    return {"error": "Rate limit exceeded. Please try again later."}
                elif response.status != 200:
                    return {"error": "Failed to fetch price history"}

                data = await response.json()

                # Process historical data
                history = []
                for i in range(min(len(data['prices']), days)):
                    timestamp = int(data['prices'][i][0] / 1000)
                    price = data['prices'][i][1]
                    volume = data['total_volumes'][i][1] if i < len(data['total_volumes']) else 0
                    
                    # Calculate 24h change
                    prev_price = data['prices'][i-1][1] if i > 0 else price
                    change_24h = ((price - prev_price) / prev_price) * 100

                    history.append({
                        "timestamp": timestamp,
                        "price": price,
                        "volume": volume,
                        "change_24h": change_24h
                    })

                return {
                    "symbol": symbol.upper(),
                    "history": history
                }

        except Exception as e:
            logger.error(f"Error fetching price history for {symbol}: {e}")
            return {"error": "Failed to fetch price history"}

    async def get_price(self, symbol: str) -> Dict[str, Any]:
        """Get current price and 24h stats for a cryptocurrency"""
        try:
            # Convert common symbols to CoinGecko IDs
            coin_id = await self._get_coin_id(symbol.lower())
            if not coin_id:
                return {"error": f"Cryptocurrency {symbol} not found"}

            # Fetch price data
            url = f"{self.base_url}/simple/price"
            params = {
                "ids": coin_id,
                "vs_currencies": "usd",
                "include_24hr_change": "true",
                "include_24hr_vol": "true",
                "include_market_cap": "true"
            }

            async with self.session.get(url, params=params) as response:
                if response.status == 429:
                    return {"error": "Rate limit exceeded. Please try again later."}
                elif response.status != 200:
                    return {"error": "Failed to fetch price data"}

                data = await response.json()
                if coin_id not in data:
                    return {"error": f"No price data available for {symbol}"}

                price_data = data[coin_id]
                return {
                    "symbol": symbol.upper(),
                    "price_usd": price_data["usd"],
                    "change_24h": price_data.get("usd_24h_change", 0),
                    "volume_24h": price_data.get("usd_24h_vol", 0),
                    "market_cap": price_data.get("usd_market_cap", 0)
                }

        except Exception as e:
            logger.error(f"Error fetching price for {symbol}: {e}")
            return {"error": "Failed to fetch price data"}

    async def _get_coin_id(self, symbol: str) -> Optional[str]:
        """Convert common trading symbol to CoinGecko coin ID"""
        # Common mappings
        mappings = {
            "btc": "bitcoin",
            "eth": "ethereum",
            "usdt": "tether",
            "bnb": "binancecoin",
            "xrp": "ripple",
            "ada": "cardano",
            "doge": "dogecoin",
            "sol": "solana"
        }

        # Return direct mapping if exists
        if symbol in mappings:
            return mappings[symbol]

        # Search in CoinGecko API
        try:
            url = f"{self.base_url}/search"
            params = {"query": symbol}
            
            async with self.session.get(url, params=params) as response:
                if response.status != 200:
                    return None

                data = await response.json()
                coins = data.get("coins", [])
                
                if not coins:
                    return None

                # Return the first matching coin ID
                return coins[0]["id"]

        except Exception as e:
            logger.error(f"Error searching for coin ID: {e}")
            return None

# Create singleton instance
price_service = PriceService() 