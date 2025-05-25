from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from datetime import datetime
from enum import Enum

class SubscriptionTier(str, Enum):
    FREE = "free"
    PREMIUM = "premium"
    PRO = "pro"

class AlertCondition(str, Enum):
    ABOVE = "above"
    BELOW = "below"

class UserBase(BaseModel):
    telegram_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None

class UserCreate(UserBase):
    pass

class User(UserBase):
    id: str
    subscription_tier: SubscriptionTier = SubscriptionTier.FREE
    notification_settings: Dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class AlertBase(BaseModel):
    symbol: str
    price_threshold: float
    condition: AlertCondition

class AlertCreate(AlertBase):
    pass

class Alert(AlertBase):
    id: str
    user_id: str
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class SubscriptionBase(BaseModel):
    symbol: str
    news_enabled: bool = True
    price_alerts: bool = True

class SubscriptionCreate(SubscriptionBase):
    pass

class Subscription(SubscriptionBase):
    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class PortfolioBase(BaseModel):
    symbol: str
    quantity: float
    average_price: float

class PortfolioCreate(PortfolioBase):
    pass

class Portfolio(PortfolioBase):
    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class PriceAlert(BaseModel):
    symbol: str
    current_price: float
    price_change_24h: float
    market_cap: float
    volume_24h: float

class NewsItem(BaseModel):
    title: str
    content: str
    source: str
    url: str
    sentiment: Optional[float] = None
    published_at: datetime

class MarketData(BaseModel):
    symbol: str
    price: float
    price_change_24h: float
    market_cap: float
    volume_24h: float
    high_24h: float
    low_24h: float
    last_updated: datetime 