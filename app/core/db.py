from prisma import Prisma
from typing import Optional, Any, Dict, List
from loguru import logger
import asyncio
from datetime import datetime

class Database:
    _instance: Optional['Database'] = None
    _lock = asyncio.Lock()
    _initialized = False
    
    def __new__(cls):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self.prisma = Prisma()
            self._initialized = True
    
    async def connect(self):
        """Connect to the database"""
        if not self.prisma.is_connected():
            await self.prisma.connect()
    
    async def disconnect(self):
        """Disconnect from the database"""
        if self.prisma.is_connected():
            await self.prisma.disconnect()
    
    async def execute_raw(self, query: str, *args):
        """Execute a raw SQL query"""
        return await self.prisma.query_raw(query, *args)
    
    # Add other database operations as needed
    
    # Singleton instance
db = Database()

# Example usage:
# from app.core.db import db
# await db.connect()
# result = await db.prisma.user.find_many()
# await db.disconnect()
