from typing import List, Optional, Dict, Any, Union
import httpx
from datetime import datetime, timedelta
from loguru import logger
import aiohttp
import random
import json

from env import env
from app.models.schemas import NewsItem
from app.services.cache_service import CacheService

class NewsService:
    _instance: Optional['NewsService'] = None
    _initialized: bool = False
    
    # API Endpoints
    COINDESK_BASE_URL = "https://api.coindesk.com/v2"
    CRYPTOCOMPARE_BASE_URL = "https://min-api.cryptocompare.com/data/v2"
    
    # Cache settings
    NEWS_CACHE_TTL = 60  # 1 minute
    
    # Service flags
    use_coindesk: bool = True
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(NewsService, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self.cache = CacheService()
            self.session: Optional[aiohttp.ClientSession] = None
            self._initialized = True

    async def initialize(self):
        """Initialize the HTTP session"""
        if not self.session:
            self.session = aiohttp.ClientSession()

    async def close(self):
        """Close the HTTP session"""
        if self.session:
            await self.session.close()
            self.session = None

    async def _fetch_news_data(self) -> List[Dict[str, Any]]:
        """Fetch news data from the API"""
        cache_key = "crypto_news_data"
        
        # Try to get from cache first
        cached_data = await self.cache.get_key(cache_key)
        if cached_data:
            return cached_data
            
        try:
            if not self.session:
                await self.initialize()
            
            news_items = []
            
            # Try CoinDesk first if enabled and API key is available
            if self.use_coindesk and env.COINDESK_API_KEY:
                try:
                    coindesk_news = await self._fetch_coindesk_news()
                    if coindesk_news:
                        news_items.extend(coindesk_news)
                except Exception as e:
                    logger.warning(f"Failed to fetch from CoinDesk: {e}")
            
            # Fall back to CryptoCompare if needed
            if not news_items:
                try:
                    crypto_compare_news = await self._fetch_cryptocompare_news()
                    if crypto_compare_news:
                        news_items.extend(crypto_compare_news)
                except Exception as e:
                    logger.error(f"Failed to fetch from CryptoCompare: {e}")
            
            # Cache the results
            if news_items:
                await self.cache.set_key(cache_key, news_items, expiry=self.NEWS_CACHE_TTL)
            
            return news_items
                
        except Exception as e:
            logger.error(f"Error fetching news data: {e}")
            return []
            
    async def _fetch_coindesk_news(self) -> List[Dict[str, Any]]:
        """Fetch news from CoinDesk API"""
        url = f"{self.COINDESK_BASE_URL}/news/btc-macro/1"
        headers = {
            "accept": "application/json",
            "x-bloomburg": "false"
        }
        
        if env.COINDESK_API_KEY:
            headers["Authorization"] = f"Bearer {env.COINDESK_API_KEY}"
        
        async with self.session.get(url, headers=headers) as response:
            if response.status != 200:
                logger.error(f"CoinDesk API error: {response.status}")
                return []
                
            data = await response.json()
            articles = data.get("data", {}).get("news", [])
            
            return [{
                "title": article.get("title", ""),
                "source": "CoinDesk",
                "url": article.get("url", ""),
                "imageurl": article.get("thumbnail", ""),
                "body": article.get("description", ""),
                "source_info": {"name": "CoinDesk"},
                "published_on": int(datetime.fromisoformat(article.get("publishedAt", "").replace("Z", "+00:00")).timestamp())
            } for article in articles]
    
    async def _fetch_cryptocompare_news(self) -> List[Dict[str, Any]]:
        """Fetch news from CryptoCompare API"""
        url = f"{self.CRYPTOCOMPARE_BASE_URL}/news/"
        
        async with self.session.get(url) as response:
            if response.status != 200:
                logger.error(f"CryptoCompare API error: {response.status}")
                return []
                
            data = await response.json()
            if data.get("Type") == 100 and "Data" in data:
                return data["Data"]
            return []

    async def get_headlines(self, limit: int = 5) -> List[Dict[str, str]]:
        """
        Get top headlines with source and URL
        
        Args:
            limit: Number of headlines to return (default: 5)
            
        Returns:
            List of dicts with title, source, and url
        """
        try:
            news_data = await self._fetch_news_data()
            if not news_data:
                return []
                
            headlines = []
            for item in news_data[:limit]:
                headlines.append({
                    "title": item.get("title", ""),
                    "source": item.get("source_info", {}).get("name", "Unknown"),
                    "url": item.get("url", "#")
                })
                
            return headlines
            
        except Exception as e:
            logger.error(f"Error getting headlines: {e}")
            return []

    async def get_news(self, limit: int = 3) -> List[Dict[str, Any]]:
        """
        Get detailed news with image and short description
        
        Args:
            limit: Number of news items to return (default: 3)
            
        Returns:
            List of dicts with title, source, url, image, and description
        """
        try:
            news_data = await self._fetch_news_data()
            if not news_data:
                return []
                
            # Shuffle and pick top items to get variety
            shuffled_news = random.sample(news_data, min(limit * 2, len(news_data)))
            
            news_items = []
            for item in shuffled_news[:limit]:
                # Get first 2-3 sentences from the body
                body = item.get("body", "")
                sentences = [s.strip() for s in body.split('.') if s.strip()]
                short_description = '. '.join(sentences[:3]) + ('.' if len(sentences) > 3 else '')
                
                news_items.append({
                    "title": item.get("title", ""),
                    "source": item.get("source_info", {}).get("name", "Unknown"),
                    "url": item.get("url", "#"),
                    "image": item.get("imageurl", ""),
                    "description": short_description
                })
                
            return news_items
            
        except Exception as e:
            logger.error(f"Error getting news: {e}")
            return []

    async def get_trending_news(self) -> List[Dict[str, Any]]:
        """
        Get trending crypto news (compatibility method)
        
        Returns:
            List of dicts with title, source, and url
        """
        headlines = await self.get_headlines(limit=5)
        return [
            {
                "title": item["title"],
                "source": item["source"],
                "url": item["url"],
                "published_at": datetime.utcnow()
            }
            for item in headlines
        ]

# Create singleton instance
news_service = NewsService() 