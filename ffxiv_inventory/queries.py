"""Inventory query and comparison functionality."""

from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import Snapshot, SnapshotItem, ItemInfo


class InventoryQuery:
    """Query and compare inventory snapshots."""
    
    @staticmethod
    async def get_snapshot(
        session: AsyncSession,
        snapshot_id: int,
        with_items: bool = True,
    ) -> Optional[Snapshot]:
        """Get a snapshot by ID.
        
        Args:
            session: Database session
            snapshot_id: Snapshot ID
            with_items: Whether to load items
            
        Returns:
            Snapshot object or None
        """
        stmt = select(Snapshot).where(Snapshot.id == snapshot_id)
        
        if with_items:
            stmt = stmt.options(selectinload(Snapshot.items))
        
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
    
    @staticmethod
    async def list_snapshots(
        session: AsyncSession,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Snapshot]:
        """List all snapshots.
        
        Args:
            session: Database session
            limit: Maximum number of snapshots to return
            offset: Number of snapshots to skip
            
        Returns:
            List of Snapshot objects
        """
        stmt = (
            select(Snapshot)
            .order_by(Snapshot.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())
    
    @staticmethod
    async def get_snapshot_items_enriched(
        session: AsyncSession,
        snapshot_id: int,
    ) -> list[dict]:
        """Get snapshot items with enriched information.
        
        Args:
            session: Database session
            snapshot_id: Snapshot ID
            
        Returns:
            List of dictionaries with item info
        """
        stmt = (
            select(SnapshotItem, ItemInfo)
            .outerjoin(ItemInfo, SnapshotItem.item_id == ItemInfo.item_id)
            .where(SnapshotItem.snapshot_id == snapshot_id)
            .order_by(SnapshotItem.item_id)
        )
        result = await session.execute(stmt)
        
        items = []
        for snapshot_item, item_info in result:
            item_dict = {
                "item_id": snapshot_item.item_id,
                "quantity": snapshot_item.quantity,
            }
            
            if item_info:
                item_dict.update({
                    "name": item_info.name,
                    "icon_url": item_info.icon_url,
                    "category": item_info.category,
                    "item_level": item_info.item_level,
                })
            
            items.append(item_dict)
        
        return items
    
    @staticmethod
    async def compare_snapshots(
        session: AsyncSession,
        snapshot_id_a: int,
        snapshot_id_b: int,
    ) -> dict[str, list[dict]]:
        """Compare two snapshots and show differences.
        
        Args:
            session: Database session
            snapshot_id_a: First snapshot ID (older)
            snapshot_id_b: Second snapshot ID (newer)
            
        Returns:
            Dictionary with 'added', 'removed', and 'changed' items
        """
        # Get items from both snapshots
        stmt_a = select(SnapshotItem).where(SnapshotItem.snapshot_id == snapshot_id_a)
        result_a = await session.execute(stmt_a)
        items_a = {item.item_id: item.quantity for item in result_a.scalars()}
        
        stmt_b = select(SnapshotItem).where(SnapshotItem.snapshot_id == snapshot_id_b)
        result_b = await session.execute(stmt_b)
        items_b = {item.item_id: item.quantity for item in result_b.scalars()}
        
        # Find differences
        added_items = []
        removed_items = []
        changed_items = []
        
        # Items in B but not in A (added)
        for item_id, quantity in items_b.items():
            if item_id not in items_a:
                added_items.append({"item_id": item_id, "quantity": quantity})
        
        # Items in A but not in B (removed)
        for item_id, quantity in items_a.items():
            if item_id not in items_b:
                removed_items.append({"item_id": item_id, "quantity": quantity})
        
        # Items in both but with different quantities (changed)
        for item_id in set(items_a.keys()) & set(items_b.keys()):
            qty_a = items_a[item_id]
            qty_b = items_b[item_id]
            if qty_a != qty_b:
                changed_items.append({
                    "item_id": item_id,
                    "old_quantity": qty_a,
                    "new_quantity": qty_b,
                    "change": qty_b - qty_a,
                })
        
        # Enrich with item info
        all_item_ids = list(set(items_a.keys()) | set(items_b.keys()))
        stmt_info = select(ItemInfo).where(ItemInfo.item_id.in_(all_item_ids))
        result_info = await session.execute(stmt_info)
        item_info_map = {info.item_id: info for info in result_info.scalars()}
        
        def enrich_item(item: dict) -> dict:
            """Add item info to diff item."""
            item_id = item["item_id"]
            if item_id in item_info_map:
                info = item_info_map[item_id]
                item["name"] = info.name
                item["icon_url"] = info.icon_url
                item["category"] = info.category
            return item
        
        return {
            "added": [enrich_item(item) for item in added_items],
            "removed": [enrich_item(item) for item in removed_items],
            "changed": [enrich_item(item) for item in changed_items],
        }
    
    @staticmethod
    async def get_current_inventory(
        session: AsyncSession,
        up_to_snapshot_id: Optional[int] = None,
    ) -> dict[int, int]:
        """Get current inventory state by aggregating all snapshots.
        
        This is a simplified version. In a real application, you might want
        to track adds/removes explicitly rather than just aggregating quantities.
        
        Args:
            session: Database session
            up_to_snapshot_id: Only include snapshots up to this ID
            
        Returns:
            Dictionary mapping item_id to total quantity
        """
        stmt = select(Snapshot.id).order_by(Snapshot.created_at.desc())
        
        if up_to_snapshot_id:
            stmt = stmt.where(Snapshot.id <= up_to_snapshot_id)
        
        stmt = stmt.limit(1)
        result = await session.execute(stmt)
        latest_snapshot_id = result.scalar_one_or_none()
        
        if not latest_snapshot_id:
            return {}
        
        # Get items from latest snapshot
        stmt_items = select(SnapshotItem).where(
            SnapshotItem.snapshot_id == latest_snapshot_id
        )
        result_items = await session.execute(stmt_items)
        
        return {item.item_id: item.quantity for item in result_items.scalars()}
