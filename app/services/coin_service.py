from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import httpx
from loguru import logger

from app.models.coin import CoinCreate, CoinUpdate, CoinInDB
from app.services.cache_service import CacheService
from app.core.db import db

class CoinService:
    _instance: Optional['CoinService'] = None
    _initialized: bool = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(CoinService, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self.cache = CacheService()
            self._initialized = True
    
    async def get_coins(
        self, 
        page: int = 1, 
        per_page: int = 10, 
        force_refresh: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get paginated list of coins with caching
        """
        cache_key = f"coins_page_{page}_per_{per_page}"
        
        # Try to get from cache first if not forcing refresh
        if not force_refresh:
            cached_data = await self.cache.get_key(cache_key)
            if cached_data:
                return cached_data
        
        # Calculate skip for pagination
        skip = (page - 1) * per_page
        
        # Get from database
        db_coins = await db.prisma.coin.find_many(
            skip=skip,
            take=per_page,
            order={"market_cap": "desc"}  # Default sort by market cap
        )
        
        # If no coins in DB or forcing refresh, fetch from API
        if not db_coins or force_refresh:
            coins_data = await self._fetch_coins_from_api()
            
            # Update database
            await self._update_coins_in_db(coins_data)
            
            # Get fresh data from DB after update
            db_coins = await db.prisma.coin.find_many(
                skip=skip,
                take=per_page,
                order={"market_cap": "desc"}
            )
        
        # Format response
        coins = [{
            "id": coin.id,
            "coin_id": coin.coin_id,
            "symbol": coin.symbol.upper(),
            "name": coin.name,
            "current_price": coin.current_price,
            "price_change_percentage_24h": coin.price_change_percentage_24h,
            "market_cap": coin.market_cap,
            "total_volume": coin.total_volume,
            "image": coin.image,
            "last_updated": coin.last_updated.isoformat()
        } for coin in db_coins]
        
        # Cache the results for 5 minutes
        await self.cache.set_key(cache_key, coins, expiry=300)
        
        return coins
    
    async def _fetch_coins_from_api(self) -> List[Dict[str, Any]]:
        """Fetch coins from CoinGecko API"""
        url = "https://api.coingecko.com/api/v3/coins/markets"
        params = {
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": 250,
            "page": 1,
            "sparkline": False,
            "price_change_percentage": "24h"
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Error fetching coins from API: {e}")
            return []
    
    async def _update_coins_in_db(self, coins_data: List[Dict[str, Any]]) -> None:
        """Update coins in the database"""
        if not coins_data:
            return
            
        for coin_data in coins_data:
            coin_id = coin_data.get('id')
            if not coin_id:
                continue
                
            # Prepare coin data
            coin_update = {
                "symbol": coin_data.get('symbol', '').lower(),
                "name": coin_data.get('name', ''),
                "current_price": coin_data.get('current_price'),
                "price_change_percentage_24h": coin_data.get('price_change_percentage_24h'),
                "market_cap": coin_data.get('market_cap'),
                "total_volume": coin_data.get('total_volume'),
                "image": coin_data.get('image'),
                "last_updated": datetime.utcnow()
            }
            
            # Update or create coin
            # Check if coin exists
            existing = await db.prisma.coin.find_unique(
                where={"coin_id": coin_id}
            )
            
            if existing:
                # Update existing coin
                await db.prisma.coin.update(
                    where={"coin_id": coin_id},
                    data=coin_update
                )
            else:
                # Create new coin
                await db.prisma.coin.create(
                    data={"coin_id": coin_id, **coin_update}
                )

# Create singleton instance
coin_service = CoinService()
