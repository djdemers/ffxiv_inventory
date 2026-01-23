"""Import functionality for JSON and CSV inventory snapshots."""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Snapshot, SnapshotItem
from .xivapi import XIVAPIClient


class SnapshotImporter:
    """Import inventory snapshots from JSON or CSV files."""
    
    def __init__(self, xivapi_client: XIVAPIClient):
        """Initialize importer.
        
        Args:
            xivapi_client: XIVAPI client for item enrichment
        """
        self.xivapi_client = xivapi_client
    
    async def import_json(
        self,
        session: AsyncSession,
        file_path: Path,
        snapshot_name: str | None = None,
        enrich: bool = True,
    ) -> Snapshot:
        """Import inventory snapshot from JSON file.
        
        Expected JSON format:
        [
            {"item_id": 123, "quantity": 5},
            {"item_id": 456, "quantity": 10}
        ]
        
        Args:
            session: Database session
            file_path: Path to JSON file
            snapshot_name: Optional name for the snapshot
            enrich: Whether to enrich items from XIVAPI
            
        Returns:
            Created Snapshot object
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if not isinstance(data, list):
            raise ValueError("JSON must be a list of items")
        
        # Create snapshot
        snapshot = Snapshot(
            name=snapshot_name or file_path.stem,
            created_at=datetime.now(timezone.utc),
        )
        session.add(snapshot)
        await session.flush()  # Get snapshot ID
        
        # Add items
        for item_data in data:
            if not isinstance(item_data, dict):
                raise ValueError("Each item must be a dictionary")
            
            item_id = item_data.get("item_id")
            quantity = item_data.get("quantity", 1)
            
            if not item_id:
                raise ValueError("Each item must have 'item_id'")
            
            snapshot_item = SnapshotItem(
                snapshot_id=snapshot.id,
                item_id=item_id,
                quantity=quantity,
            )
            session.add(snapshot_item)
        
        await session.commit()
        
        # Enrich items if requested
        if enrich:
            await self._enrich_snapshot_items(session, snapshot)
        
        # Refresh to get relationships
        await session.refresh(snapshot)
        return snapshot
    
    async def import_csv(
        self,
        session: AsyncSession,
        file_path: Path,
        snapshot_name: str | None = None,
        enrich: bool = True,
    ) -> Snapshot:
        """Import inventory snapshot from CSV file.
        
        Expected CSV format:
        item_id,quantity
        123,5
        456,10
        
        Args:
            session: Database session
            file_path: Path to CSV file
            snapshot_name: Optional name for the snapshot
            enrich: Whether to enrich items from XIVAPI
            
        Returns:
            Created Snapshot object
        """
        items = []
        
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            # Validate headers
            if 'item_id' not in reader.fieldnames:
                raise ValueError("CSV must have 'item_id' column")
            
            for row in reader:
                item_id = int(row['item_id'])
                quantity = int(row.get('quantity', 1))
                items.append({"item_id": item_id, "quantity": quantity})
        
        # Create snapshot
        snapshot = Snapshot(
            name=snapshot_name or file_path.stem,
            created_at=datetime.now(timezone.utc),
        )
        session.add(snapshot)
        await session.flush()
        
        # Add items
        for item_data in items:
            snapshot_item = SnapshotItem(
                snapshot_id=snapshot.id,
                item_id=item_data["item_id"],
                quantity=item_data["quantity"],
            )
            session.add(snapshot_item)
        
        await session.commit()
        
        # Enrich items if requested
        if enrich:
            await self._enrich_snapshot_items(session, snapshot)
        
        # Refresh to get relationships
        await session.refresh(snapshot)
        return snapshot
    
    async def _enrich_snapshot_items(
        self,
        session: AsyncSession,
        snapshot: Snapshot,
    ) -> None:
        """Enrich all items in a snapshot from XIVAPI.
        
        Args:
            session: Database session
            snapshot: Snapshot to enrich
        """
        # Get all unique item IDs in snapshot
        stmt = select(SnapshotItem.item_id).where(
            SnapshotItem.snapshot_id == snapshot.id
        ).distinct()
        result = await session.execute(stmt)
        item_ids = [row[0] for row in result]
        
        # Enrich items
        await self.xivapi_client.enrich_items(session, item_ids)
