"""XIVAPI client for item enrichment with caching."""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ItemInfo


class XIVAPIClient:
    """Client for XIVAPI with built-in caching."""
    
    def __init__(
        self,
        base_url: str = "https://xivapi.com",
        cache_ttl_days: int = 30,
        rate_limit_per_second: int = 20,
    ):
        """Initialize XIVAPI client.
        
        Args:
            base_url: Base URL for XIVAPI
            cache_ttl_days: Days to cache item info before refreshing
            rate_limit_per_second: Maximum requests per second
        """
        self.base_url = base_url
        self.cache_ttl = timedelta(days=cache_ttl_days)
        self.rate_limit = rate_limit_per_second
        self._last_request_time: float = 0.0
        self._min_interval = 1.0 / rate_limit_per_second
    
    async def _rate_limit_wait(self) -> None:
        """Enforce rate limiting."""
        now = asyncio.get_event_loop().time()
        time_since_last = now - self._last_request_time
        if time_since_last < self._min_interval:
            await asyncio.sleep(self._min_interval - time_since_last)
        self._last_request_time = asyncio.get_event_loop().time()
    
    async def get_item_info(
        self,
        session: AsyncSession,
        item_id: int,
        force_refresh: bool = False,
    ) -> Optional[ItemInfo]:
        """Get item information with caching.
        
        Args:
            session: Database session
            item_id: XIVAPI item ID
            force_refresh: Force refresh from API even if cached
            
        Returns:
            ItemInfo object or None if not found
        """
        # Check cache first
        if not force_refresh:
            stmt = select(ItemInfo).where(ItemInfo.item_id == item_id)
            result = await session.execute(stmt)
            cached_item = result.scalar_one_or_none()
            
            if cached_item:
                # Check if cache is still valid
                age = datetime.now(timezone.utc) - cached_item.last_updated
                if age < self.cache_ttl:
                    return cached_item
        
        # Fetch from API
        await self._rate_limit_wait()
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{self.base_url}/item/{item_id}",
                    timeout=10.0,
                )
                response.raise_for_status()
                data = response.json()
                
                # Parse response
                item_info = ItemInfo(
                    item_id=item_id,
                    name=data.get("Name", f"Unknown Item {item_id}"),
                    icon_url=self._get_icon_url(data),
                    category=self._get_category(data),
                    item_level=data.get("LevelItem", 0),
                    last_updated=datetime.now(timezone.utc),
                )
                
                # Merge into database (upsert)
                await session.merge(item_info)
                await session.commit()
                
                return item_info
                
            except (httpx.HTTPError, KeyError, ValueError) as e:
                # Log error but don't fail completely
                print(f"Error fetching item {item_id} from XIVAPI: {e}")
                
                # Return cached data if available, even if expired
                stmt = select(ItemInfo).where(ItemInfo.item_id == item_id)
                result = await session.execute(stmt)
                return result.scalar_one_or_none()
    
    def _get_icon_url(self, data: dict) -> Optional[str]:
        """Extract icon URL from XIVAPI response.
        
        Args:
            data: XIVAPI response data
            
        Returns:
            Icon URL or None
        """
        icon_path = data.get("Icon")
        if icon_path:
            # XIVAPI provides relative paths, construct full URL
            return f"{self.base_url}{icon_path}"
        return None
    
    def _get_category(self, data: dict) -> Optional[str]:
        """Extract item category from XIVAPI response.
        
        Args:
            data: XIVAPI response data
            
        Returns:
            Category name or None
        """
        item_ui_category = data.get("ItemUICategory")
        if item_ui_category and isinstance(item_ui_category, dict):
            return item_ui_category.get("Name")
        return None
    
    async def enrich_items(
        self,
        session: AsyncSession,
        item_ids: list[int],
        force_refresh: bool = False,
    ) -> dict[int, ItemInfo]:
        """Batch enrich multiple items.
        
        Args:
            session: Database session
            item_ids: List of item IDs to enrich
            force_refresh: Force refresh from API
            
        Returns:
            Dictionary mapping item_id to ItemInfo
        """
        results: dict[int, ItemInfo] = {}
        
        for item_id in item_ids:
            item_info = await self.get_item_info(session, item_id, force_refresh)
            if item_info:
                results[item_id] = item_info
        
        return results
