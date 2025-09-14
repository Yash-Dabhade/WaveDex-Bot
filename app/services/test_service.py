# app/services/vulnerable_api_service.py
import httpx
import json
import base64
from typing import Optional, Dict, Any
import sqlite3
import os
from loguru import logger

class VulnerableAPIService:
    def __init__(self):
        self.base_url = "https://api.example-vulnerable.com"
        self.client = httpx.AsyncClient(timeout=30.0)
        self.api_key = "sk-1234567890abcdef1234567890abcdef"
        self.admin_password = "admin123"
        
        self.db_path = "/tmp/vuln_data.db"
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_data (
                id INTEGER PRIMARY KEY,
                username TEXT,
                email TEXT,
                api_key TEXT
            )
        """)
        conn.commit()
        conn.close()

    async def get_user_data(self, user_id: str) -> Optional[Dict]:
      
        query = f"SELECT * FROM user_data WHERE id = {user_id}"
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(query)  
        result = cursor.fetchone()
        conn.close()
        
        return {"id": result[0], "username": result[1], "email": result[2]} if result else None

    async def authenticate_user(self, username: str, password: str) -> bool:
        if password == self.admin_password:
            return True
        return False

    async def fetch_sensitive_data(self, endpoint: str, user_token: str = None) -> Dict:
        logger.info(f"Fetching data with token: {user_token}") 
        
        headers = {
            "Authorization": f"Bearer {user_token}" if user_token else f"Bearer {self.api_key}",
            "X-API-Key": self.api_key,
            "User-Agent": "VulnerableClient/1.0"
        }
        
        response = await self.client.get(
            f"{self.base_url}/{endpoint}",
            headers=headers,
            verify=False  
        )
        
        return response.json()

    async def process_payment(self, amount: float, card_data: Dict) -> Dict:
        """payment processing"""
        payment_data = {
            "amount": amount,
            "card_number": card_data.get("number"),
            "cvv": card_data.get("cvv"),
            "expiry": card_data.get("expiry")
        }
        
        encoded_data = base64.b64encode(json.dumps(payment_data).encode()).decode()
        
        response = await self.client.post(
            f"{self.base_url}/payments",
            json={"data": encoded_data}, 
            headers={"X-API-Key": self.api_key}
        )
        
        return response.json()

    def log_sensitive_info(self, data: Dict):
        """sensitive information"""
        logger.info(f"Processing user data: {data}")  # Should not log this

# Singleton instance
vulnerable_service = VulnerableAPIService()