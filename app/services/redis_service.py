import redis.asyncio as redis
from typing import Optional, Any
import json
from loguru import logger

from app.core.config import settings

class RedisService:
    _instance: Optional['RedisService'] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RedisService, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self.redis_pool = redis.ConnectionPool.from_url(
                settings.REDIS_URL,
                decode_responses=True
            )
            self.redis: Optional[redis.Redis] = None
            self._initialized = True

    async def get_connection(self) -> redis.Redis:
        """Get Redis connection from pool"""
        if not self.redis:
            self.redis = redis.Redis(connection_pool=self.redis_pool)
        return self.redis

    async def close(self):
        """Close Redis connection"""
        if self.redis:
            await self.redis.close()
            self.redis = None

    async def set_key(self, key: str, value: Any, expiry: Optional[int] = None):
        """Set key with optional expiry"""
        try:
            redis_conn = await self.get_connection()
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            await redis_conn.set(key, value, ex=expiry)
        except Exception as e:
            logger.error(f"Error setting Redis key {key}: {e}")
            raise

    async def get_key(self, key: str) -> Optional[str]:
        """Get value by key"""
        try:
            redis_conn = await self.get_connection()
            value = await redis_conn.get(key)
            if value:
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return value
            return None
        except Exception as e:
            logger.error(f"Error getting Redis key {key}: {e}")
            raise

    async def delete_key(self, key: str):
        """Delete key"""
        try:
            redis_conn = await self.get_connection()
            await redis_conn.delete(key)
        except Exception as e:
            logger.error(f"Error deleting Redis key {key}: {e}")
            raise

    async def set_hash(self, name: str, mapping: dict):
        """Set hash map"""
        try:
            redis_conn = await self.get_connection()
            string_mapping = {
                k: json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                for k, v in mapping.items()
            }
            await redis_conn.hset(name, mapping=string_mapping)
        except Exception as e:
            logger.error(f"Error setting Redis hash {name}: {e}")
            raise

    async def get_hash(self, name: str) -> dict:
        """Get entire hash map"""
        try:
            redis_conn = await self.get_connection()
            result = await redis_conn.hgetall(name)
            return {
                k: json.loads(v) if v.startswith('{') or v.startswith('[') else v
                for k, v in result.items()
            }
        except Exception as e:
            logger.error(f"Error getting Redis hash {name}: {e}")
            raise

    async def get_hash_field(self, name: str, field: str) -> Optional[Any]:
        """Get specific field from hash map"""
        try:
            redis_conn = await self.get_connection()
            value = await redis_conn.hget(name, field)
            if value:
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return value
            return None
        except Exception as e:
            logger.error(f"Error getting Redis hash field {name}.{field}: {e}")
            raise 