from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

class CoinBase(BaseModel):
    coin_id: str
    symbol: str
    name: str
    current_price: Optional[float] = None
    price_change_percentage_24h: Optional[float] = None
    market_cap: Optional[float] = None
    total_volume: Optional[float] = None
    image: Optional[str] = None
    last_updated: datetime

class CoinCreate(CoinBase):
    pass

class CoinUpdate(CoinBase):
    pass

class CoinInDB(CoinBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
