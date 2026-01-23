"""Example script showing how to use the FFXIV inventory library."""

import asyncio
from pathlib import Path

from ffxiv_inventory.database import get_database
from ffxiv_inventory.importer import SnapshotImporter
from ffxiv_inventory.queries import InventoryQuery
from ffxiv_inventory.xivapi import XIVAPIClient


async def main() -> None:
    """Run example operations."""
    # Initialize database
    db = get_database("sqlite+aiosqlite:///./example_inventory.db")
    await db.init_db()
    
    # Create clients
    xivapi_client = XIVAPIClient()
    importer = SnapshotImporter(xivapi_client)
    
    # Import a JSON snapshot
    print("Importing JSON snapshot...")
    async for session in db.get_session():
        snapshot = await importer.import_json(
            session,
            Path("examples/example_inventory.json"),
            snapshot_name="Example Snapshot 1",
            enrich=True,
        )
        print(f"Created snapshot {snapshot.id}: {snapshot.name}")
        
        # Get items with enrichment
        items = await InventoryQuery.get_snapshot_items_enriched(session, snapshot.id)
        print(f"\nSnapshot contains {len(items)} items:")
        for item in items:
            print(f"  - {item.get('name', 'Unknown')}: {item['quantity']}")
    
    # Import a CSV snapshot
    print("\nImporting CSV snapshot...")
    async for session in db.get_session():
        snapshot2 = await importer.import_csv(
            session,
            Path("examples/example_inventory.csv"),
            snapshot_name="Example Snapshot 2",
            enrich=True,
        )
        print(f"Created snapshot {snapshot2.id}: {snapshot2.name}")
    
    # Compare snapshots
    print("\nComparing snapshots...")
    async for session in db.get_session():
        diff = await InventoryQuery.compare_snapshots(session, snapshot.id, snapshot2.id)
        
        if diff["added"]:
            print("Added items:")
            for item in diff["added"]:
                print(f"  + {item.get('name', 'Unknown')}: {item['quantity']}")
        
        if diff["removed"]:
            print("Removed items:")
            for item in diff["removed"]:
                print(f"  - {item.get('name', 'Unknown')}: {item['quantity']}")
        
        if diff["changed"]:
            print("Changed items:")
            for item in diff["changed"]:
                print(f"  ~ {item.get('name', 'Unknown')}: {item['old_quantity']} -> {item['new_quantity']}")
        
        if not diff["added"] and not diff["removed"] and not diff["changed"]:
            print("  No differences found")
    
    # Clean up
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
