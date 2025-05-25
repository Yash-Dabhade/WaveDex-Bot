from typing import List, Optional, Dict, Any
import httpx
from datetime import datetime, timedelta
from loguru import logger
import aiohttp

from app.core.config import settings
from app.models.schemas import NewsItem
from app.services.redis_service import RedisService

class NewsService:
    _instance: Optional['NewsService'] = None
    _initialized: bool = False
    NEWS_API_BASE_URL = "https://newsapi.org/v2"
    CRYPTOPANIC_BASE_URL = "https://cryptopanic.com/api/v1"
    NEWS_CACHE_TTL = 3600  # 1 hour

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(NewsService, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self.news_api_key = settings.NEWS_API_KEY
            self.cryptopanic_api_key = settings.CRYPTOPANIC_API_KEY
            self.redis = RedisService()
            
            # Initialize HTTP clients
            self.news_api_client = httpx.AsyncClient(
                base_url=self.NEWS_API_BASE_URL,
                timeout=30.0,
                headers={"X-Api-Key": self.news_api_key}
            )
            
            self.cryptopanic_client = httpx.AsyncClient(
                base_url=self.CRYPTOPANIC_BASE_URL,
                timeout=30.0,
                params={"auth_token": self.cryptopanic_api_key}
            )
            
            self.base_url = self.CRYPTOPANIC_BASE_URL
            self.session: Optional[aiohttp.ClientSession] = None
            
            self._initialized = True

    async def initialize(self):
        """Initialize the HTTP session"""
        if not self.session:
            self.session = aiohttp.ClientSession()

    async def close(self):
        """Close HTTP clients and the HTTP session"""
        await self.news_api_client.aclose()
        await self.cryptopanic_client.aclose()
        if self.session:
            await self.session.close()
            self.session = None

    async def get_news(self, symbol: str = None, limit: int = 5) -> Dict[str, Any]:
        """Get latest crypto news, optionally filtered by currency"""
        try:
            if not self.session:
                await self.initialize()

            # Build request parameters
            params = {
                "auth_token": self.cryptopanic_api_key,
                "public": "true",
                "kind": "news",
                "limit": limit
            }

            if symbol:
                params["currencies"] = symbol.upper()

            # Make API request
            async with self.session.get(f"{self.base_url}/posts/", params=params) as response:
                if response.status == 429:
                    return {"error": "Rate limit exceeded. Please try again later."}
                elif response.status != 200:
                    return {"error": "Failed to fetch news"}

                data = await response.json()
                
                if "results" not in data or not data["results"]:
                    return {"error": f"No news found{' for ' + symbol.upper() if symbol else ''}"} 

                # Process and format news items
                news_items = []
                for item in data["results"]:
                    # Convert UTC timestamp to relative time
                    published_at = datetime.fromisoformat(item["published_at"].replace('Z', '+00:00'))
                    time_diff = datetime.now(published_at.tzinfo) - published_at
                    
                    if time_diff < timedelta(hours=1):
                        relative_time = f"{int(time_diff.total_seconds() / 60)}m ago"
                    elif time_diff < timedelta(days=1):
                        relative_time = f"{int(time_diff.total_seconds() / 3600)}h ago"
                    else:
                        relative_time = f"{time_diff.days}d ago"

                    news_items.append({
                        "title": item["title"],
                        "url": item["url"],
                        "source": item["source"]["title"],
                        "published": relative_time
                    })

                return {
                    "symbol": symbol.upper() if symbol else "All Crypto",
                    "news": news_items
                }

        except Exception as e:
            logger.error(f"Error fetching news: {e}")
            return {"error": "Failed to fetch news"}

    async def _fetch_from_news_api(self, symbol: str) -> List[NewsItem]:
        """Fetch news from NewsAPI"""
        try:
            response = await self.news_api_client.get(
                "/everything",
                params={
                    "q": f"cryptocurrency {symbol}",
                    "language": "en",
                    "sortBy": "publishedAt",
                    "pageSize": 10
                }
            )
            response.raise_for_status()
            data = response.json()

            return [
                NewsItem(
                    title=article["title"],
                    content=article["description"],
                    source=article["source"]["name"],
                    url=article["url"],
                    published_at=datetime.fromisoformat(article["publishedAt"].replace("Z", "+00:00"))
                )
                for article in data.get("articles", [])
            ]

        except Exception as e:
            logger.error(f"Error fetching news from NewsAPI for {symbol}: {e}")
            return []

    async def _fetch_from_cryptopanic(self, symbol: str) -> List[NewsItem]:
        """Fetch news from CryptoPanic"""
        try:
            response = await self.cryptopanic_client.get(
                "/posts/",
                params={
                    "currencies": symbol,
                    "kind": "news",
                    "public": True
                }
            )
            response.raise_for_status()
            data = response.json()

            return [
                NewsItem(
                    title=post["title"],
                    content=post.get("metadata", {}).get("description", ""),
                    source=post["source"]["title"],
                    url=post["url"],
                    sentiment=self._get_sentiment_score(post.get("votes", {})),
                    published_at=datetime.fromisoformat(post["published_at"].replace("Z", "+00:00"))
                )
                for post in data.get("results", [])
            ]

        except Exception as e:
            logger.error(f"Error fetching news from CryptoPanic for {symbol}: {e}")
            return []

    def _get_sentiment_score(self, votes: Dict) -> float:
        """Calculate sentiment score from votes"""
        positive = votes.get("positive", 0)
        negative = votes.get("negative", 0)
        total = positive + negative

        if total == 0:
            return 0.0

        return (positive - negative) / total

    async def get_trending_news(self) -> List[NewsItem]:
        """Get trending crypto news"""
        cache_key = "news:trending"
        
        # Try to get from cache
        cached_news = await self.redis.get_key(cache_key)
        if cached_news:
            return [NewsItem(**item) for item in cached_news]

        try:
            # Fetch from CryptoPanic
            response = await self.cryptopanic_client.get(
                "/posts/",
                params={
                    "filter": "trending",
                    "kind": "news",
                    "public": True
                }
            )
            response.raise_for_status()
            data = response.json()

            trending_news = [
                NewsItem(
                    title=post["title"],
                    content=post.get("metadata", {}).get("description", ""),
                    source=post["source"]["title"],
                    url=post["url"],
                    sentiment=self._get_sentiment_score(post.get("votes", {})),
                    published_at=datetime.fromisoformat(post["published_at"].replace("Z", "+00:00"))
                )
                for post in data.get("results", [])
            ]

            # Cache the results
            await self.redis.set_key(
                cache_key,
                [news.dict() for news in trending_news],
                expiry=self.NEWS_CACHE_TTL
            )

            return trending_news

        except Exception as e:
            logger.error(f"Error fetching trending news: {e}")
            return []

# Create singleton instance
news_service = NewsService() 