from typing import Any, Dict, Optional, Union, List, Set
import json
import time
from loguru import logger

class CacheService:
    _instance: Optional['CacheService'] = None
    _initialized: bool = False
    _cache: Dict[str, Dict[str, Any]]  # key -> {'value': Any, 'expiry': float}
    _sets: Dict[str, Set[str]]  # set_name -> set of members

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(CacheService, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._cache = {}
            self._sets = {}
            self._initialized = True

    async def set_key(self, key: str, value: Any, expiry: Optional[int] = None):
        """Set key with optional expiry (in seconds)"""
        try:
            self._cache[key] = {
                'value': value,
                'expiry': time.time() + expiry if expiry else None
            }
        except Exception as e:
            logger.error(f"Error setting cache key {key}: {e}")
            raise

    async def get_key(self, key: str) -> Optional[Any]:
        """Get value by key, returns None if key doesn't exist or is expired"""
        try:
            item = self._cache.get(key)
            if item is None:
                return None
                
            # Check if item is expired
            if item['expiry'] and item['expiry'] < time.time():
                del self._cache[key]
                return None
                
            return item['value']
        except Exception as e:
            logger.error(f"Error getting cache key {key}: {e}")
            raise

    async def delete_key(self, key: str):
        """Delete key"""
        try:
            if key in self._cache:
                del self._cache[key]
        except Exception as e:
            logger.error(f"Error deleting cache key {key}: {e}")
            raise

    async def smembers(self, key: str) -> Set[str]:
        """Get all members of a set"""
        try:
            return self._sets.get(key, set())
        except Exception as e:
            logger.error(f"Error getting set members for {key}: {e}")
            raise

    async def sadd(self, key: str, *members: str):
        """Add members to a set"""
        try:
            if key not in self._sets:
                self._sets[key] = set()
            self._sets[key].update(members)
        except Exception as e:
            logger.error(f"Error adding members to set {key}: {e}")
            raise

    async def srem(self, key: str, *members: str):
        """Remove members from a set"""
        try:
            if key in self._sets:
                self._sets[key].difference_update(members)
        except Exception as e:
            logger.error(f"Error removing members from set {key}: {e}")
            raise

    async def scan_keys(self, pattern: str) -> List[str]:
        """Scan for keys matching a pattern"""
        try:
            # Simple pattern matching (only supports * at the end for now)
            if pattern.endswith('*'):
                prefix = pattern[:-1]
                return [k for k in self._cache.keys() if k.startswith(prefix)]
            elif pattern in self._cache:
                return [pattern]
            return []
        except Exception as e:
            logger.error(f"Error scanning keys with pattern {pattern}: {e}")
            raise

    async def close(self):
        """Clean up resources"""
        self._cache.clear()
        self._sets.clear()

# For backward compatibility with existing code
class RedisService(CacheService):
    """Alias for CacheService to maintain backward compatibility"""
    pass
