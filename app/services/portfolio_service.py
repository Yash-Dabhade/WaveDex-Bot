from typing import List, Dict, Optional
from loguru import logger
from decimal import Decimal
from datetime import datetime

from app.services.prisma_service import prisma_service
from app.services.coingecko_service import coingecko_service
from app.services.coinmarketcap_service import coinmarketcap_service
from app.models.schemas import Portfolio, MarketData

class PortfolioService:
    _instance: Optional['PortfolioService'] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PortfolioService, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._initialized = True

    async def get_portfolio(self, user_id: str) -> List[Dict]:
        """Get user's portfolio with current market data"""
        try:
            # Get portfolio entries
            portfolio_entries = await prisma_service.get_user_portfolio(user_id)
            
            # Get current market data for all symbols
            result = []
            for entry in portfolio_entries:
                market_data = await coingecko_service.get_price(entry["symbol"])
                if not market_data:
                    continue

                # Calculate position value and P&L
                quantity = Decimal(str(entry["quantity"]))
                avg_price = Decimal(str(entry["averagePrice"]))
                current_price = Decimal(str(market_data.price))
                
                position_value = quantity * current_price
                cost_basis = quantity * avg_price
                unrealized_pnl = position_value - cost_basis
                pnl_percentage = (
                    ((current_price - avg_price) / avg_price) * 100
                    if avg_price > 0 else Decimal('0')
                )

                result.append({
                    **entry,
                    "currentPrice": float(current_price),
                    "positionValue": float(position_value),
                    "unrealizedPnL": float(unrealized_pnl),
                    "pnlPercentage": float(pnl_percentage),
                    "priceChange24h": market_data.price_change_24h
                })

            return result

        except Exception as e:
            logger.error(f"Error getting portfolio: {e}")
            raise

    async def add_position(
        self,
        user_id: str,
        symbol: str,
        quantity: float,
        price: float
    ) -> Portfolio:
        """Add or update portfolio position"""
        try:
            symbol = symbol.upper()
            
            # Try CoinGecko first
            market_data = await coingecko_service.get_price(symbol)
            
            # If CoinGecko fails, try getting data from CoinMarketCap
            if not market_data:
                try:
                    # Get current listings from cache if available
                    cache_key = "cmc_listings"
                    cached_listings = await coinmarketcap_service.cache.get_key(cache_key)
                    
                    if not cached_listings:
                        # Fetch fresh listings
                        listings = await coinmarketcap_service.get_trending_coins(limit=5000)
                        await coinmarketcap_service.cache.set_key(cache_key, listings, expiry=600)
                        cached_listings = listings
                    
                    # Find the coin in listings
                    coin = next((c for c in cached_listings if c["symbol"] == symbol), None)
                    if coin:
                        market_data = MarketData(
                            symbol=symbol,
                            price=coin["price"],
                            price_change_24h=coin["percent_change_24h"],
                            market_cap=coin["market_cap"],
                            volume_24h=coin["volume_24h"],
                            high_24h=coin["price"] * (1 + coin["percent_change_24h"]/100),
                            low_24h=coin["price"] * (1 - coin["percent_change_24h"]/100),
                            last_updated=datetime.fromtimestamp(coin["last_updated"])
                        )
                except Exception as e:
                    logger.error(f"Error fetching CMC data for {symbol}: {e}")
            
            if not market_data:
                raise ValueError(f"Invalid symbol: {symbol}")

            # Get existing position
            portfolio = await prisma_service.get_user_portfolio(user_id)
            existing = next(
                (p for p in portfolio if p["symbol"] == symbol),
                None
            )

            if existing:
                # Update average price
                old_quantity = Decimal(str(existing["quantity"]))
                old_avg_price = Decimal(str(existing["averagePrice"]))
                new_quantity = Decimal(str(quantity))
                new_price = Decimal(str(price))

                total_quantity = old_quantity + new_quantity
                total_value = (old_quantity * old_avg_price) + (new_quantity * new_price)
                new_avg_price = total_value / total_quantity if total_quantity > 0 else Decimal('0')

                updated = await prisma_service.update_portfolio(
                    user_id=user_id,
                    symbol=symbol,
                    quantity=float(total_quantity),
                    average_price=float(new_avg_price)
                )
                return Portfolio.from_orm(updated)
            else:
                # Create new position
                created = await prisma_service.update_portfolio(
                    user_id=user_id,
                    symbol=symbol,
                    quantity=quantity,
                    average_price=price
                )
                return Portfolio.from_orm(created)

        except Exception as e:
            logger.error(f"Error adding position: {e}")
            raise

    async def remove_position(
        self,
        user_id: str,
        symbol: str,
        quantity: float
    ) -> Portfolio:
        """Remove quantity from portfolio position"""
        try:
            # Get existing position
            portfolio = await prisma_service.get_user_portfolio(user_id)
            existing = next(
                (p for p in portfolio if p["symbol"] == symbol.upper()),
                None
            )

            if not existing:
                raise ValueError(f"No position found for {symbol}")

            current_quantity = Decimal(str(existing["quantity"]))
            remove_quantity = Decimal(str(quantity))

            if remove_quantity > current_quantity:
                raise ValueError(f"Insufficient quantity. Have: {current_quantity}, Remove: {remove_quantity}")

            new_quantity = current_quantity - remove_quantity

            if new_quantity == 0:
                # Delete position if quantity becomes 0
                await prisma_service.delete_portfolio(
                    user_id=user_id,
                    symbol=symbol
                )
                return None
            else:
                # Update position with new quantity
                updated = await prisma_service.update_portfolio(
                    user_id=user_id,
                    symbol=symbol,
                    quantity=float(new_quantity),
                    average_price=existing["averagePrice"]
                )
                return Portfolio.from_orm(updated)

        except Exception as e:
            logger.error(f"Error removing position: {e}")
            raise

    async def get_portfolio_summary(self, user_id: str) -> Dict:
        """Get portfolio summary with total value and performance"""
        try:
            portfolio = await self.get_portfolio(user_id)
            
            total_value = sum(p["positionValue"] for p in portfolio)
            total_cost = sum(p["quantity"] * p["averagePrice"] for p in portfolio)
            total_pnl = sum(p["unrealizedPnL"] for p in portfolio)
            
            pnl_percentage = (
                ((total_value - total_cost) / total_cost) * 100
                if total_cost > 0 else 0
            )

            # Calculate 24h change
            total_24h_change = sum(
                p["positionValue"] * (p["priceChange24h"] / 100)
                for p in portfolio
            )
            change_24h_percentage = (
                (total_24h_change / total_value) * 100
                if total_value > 0 else 0
            )

            return {
                "totalValue": total_value,
                "totalCost": total_cost,
                "unrealizedPnL": total_pnl,
                "pnlPercentage": pnl_percentage,
                "change24h": total_24h_change,
                "change24hPercentage": change_24h_percentage,
                "positions": len(portfolio)
            }

        except Exception as e:
            logger.error(f"Error getting portfolio summary: {e}")
            raise

    async def get_watchlist_performance(self, user_id: str) -> List[Dict]:
        """Get performance data for watchlisted coins"""
        try:
            # Get portfolio entries
            portfolio_entries = await prisma_service.get_user_portfolio(user_id)
            
            # Get current market data for all symbols
            result = []
            for entry in portfolio_entries:
                market_data = await coingecko_service.get_price(entry["symbol"])
                if not market_data:
                    continue

                result.append({
                    "symbol": entry["symbol"],
                    "price": market_data.price,
                    "price_change_24h": market_data.price_change_24h,
                    "volume_24h": market_data.volume_24h,
                    "market_cap": market_data.market_cap,
                    "high_24h": market_data.high_24h,
                    "low_24h": market_data.low_24h
                })

            # Sort by 24h price change
            result.sort(key=lambda x: abs(x["price_change_24h"]), reverse=True)
            return result

        except Exception as e:
            logger.error(f"Error getting watchlist performance: {e}")
            raise

    async def get_trending_coins(self, limit: int = 10) -> List[Dict]:
        """Get top trending coins by price change"""
        try:
            # Get trending coins from CoinMarketCap
            trending = await coinmarketcap_service.get_trending_coins(limit=limit)
            
            # Sort by absolute percent change to show both top gainers and losers
            trending.sort(key=lambda x: abs(x["percent_change_24h"]), reverse=True)
            
            return trending[:limit]

        except Exception as e:
            logger.error(f"Error getting trending coins: {e}")
            raise

# Create singleton instance
portfolio_service = PortfolioService() 