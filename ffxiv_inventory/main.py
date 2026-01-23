"""FastAPI application for FFXIV inventory analysis."""

import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from . import __version__
from .database import get_database, get_db_session
from .importer import SnapshotImporter
from .queries import InventoryQuery
from .xivapi import XIVAPIClient


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifespan."""
    # Startup
    db = get_database()
    await db.init_db()
    yield
    # Shutdown
    await db.close()


# Initialize FastAPI app
app = FastAPI(
    title="FFXIV Inventory Analysis",
    description="Local Python app for FFXIV inventory analysis",
    version=__version__,
    lifespan=lifespan,
)

# Initialize XIVAPI client
xivapi_client = XIVAPIClient()


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {
        "message": "FFXIV Inventory Analysis API",
        "version": __version__,
    }


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


@app.post("/snapshots/import/json")
async def import_json_snapshot(
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
    enrich: bool = Form(True),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Import inventory snapshot from JSON file.
    
    Args:
        file: JSON file containing inventory data
        name: Optional name for the snapshot
        enrich: Whether to enrich items from XIVAPI
        session: Database session
        
    Returns:
        Created snapshot information
    """
    if not file.filename or not file.filename.endswith('.json'):
        raise HTTPException(status_code=400, detail="File must be a JSON file")
    
    # Use secure temporary file
    with tempfile.NamedTemporaryFile(mode='wb', suffix='.json', delete=False) as temp_file:
        content = await file.read()
        temp_file.write(content)
        temp_path = Path(temp_file.name)
    
    try:
        importer = SnapshotImporter(xivapi_client)
        snapshot = await importer.import_json(session, temp_path, name, enrich)
        
        return {
            "id": snapshot.id,
            "name": snapshot.name,
            "created_at": snapshot.created_at.isoformat(),
            "item_count": len(snapshot.items),
        }
    finally:
        # Clean up temp file
        temp_path.unlink(missing_ok=True)


@app.post("/snapshots/import/csv")
async def import_csv_snapshot(
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
    enrich: bool = Form(True),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Import inventory snapshot from CSV file.
    
    Args:
        file: CSV file containing inventory data
        name: Optional name for the snapshot
        enrich: Whether to enrich items from XIVAPI
        session: Database session
        
    Returns:
        Created snapshot information
    """
    if not file.filename or not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="File must be a CSV file")
    
    # Use secure temporary file
    with tempfile.NamedTemporaryFile(mode='wb', suffix='.csv', delete=False) as temp_file:
        content = await file.read()
        temp_file.write(content)
        temp_path = Path(temp_file.name)
    
    try:
        importer = SnapshotImporter(xivapi_client)
        snapshot = await importer.import_csv(session, temp_path, name, enrich)
        
        return {
            "id": snapshot.id,
            "name": snapshot.name,
            "created_at": snapshot.created_at.isoformat(),
            "item_count": len(snapshot.items),
        }
    finally:
        # Clean up temp file
        temp_path.unlink(missing_ok=True)


@app.get("/snapshots")
async def list_snapshots(
    limit: int = 100,
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    """List all snapshots.
    
    Args:
        limit: Maximum number of snapshots to return
        offset: Number of snapshots to skip
        session: Database session
        
    Returns:
        List of snapshots
    """
    snapshots = await InventoryQuery.list_snapshots(session, limit, offset)
    
    return [
        {
            "id": snapshot.id,
            "name": snapshot.name,
            "created_at": snapshot.created_at.isoformat(),
        }
        for snapshot in snapshots
    ]


@app.get("/snapshots/{snapshot_id}")
async def get_snapshot(
    snapshot_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Get a specific snapshot with all items.
    
    Args:
        snapshot_id: Snapshot ID
        session: Database session
        
    Returns:
        Snapshot details with items
    """
    snapshot = await InventoryQuery.get_snapshot(session, snapshot_id, with_items=True)
    
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    
    items = await InventoryQuery.get_snapshot_items_enriched(session, snapshot_id)
    
    return {
        "id": snapshot.id,
        "name": snapshot.name,
        "created_at": snapshot.created_at.isoformat(),
        "items": items,
    }


@app.get("/snapshots/{snapshot_id}/items")
async def get_snapshot_items(
    snapshot_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    """Get items in a snapshot with enriched information.
    
    Args:
        snapshot_id: Snapshot ID
        session: Database session
        
    Returns:
        List of items with details
    """
    # Verify snapshot exists
    snapshot = await InventoryQuery.get_snapshot(session, snapshot_id, with_items=False)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    
    return await InventoryQuery.get_snapshot_items_enriched(session, snapshot_id)


@app.get("/snapshots/compare/{snapshot_id_a}/{snapshot_id_b}")
async def compare_snapshots(
    snapshot_id_a: int,
    snapshot_id_b: int,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Compare two snapshots and show differences.
    
    Args:
        snapshot_id_a: First snapshot ID (older)
        snapshot_id_b: Second snapshot ID (newer)
        session: Database session
        
    Returns:
        Differences between snapshots
    """
    # Verify snapshots exist
    snapshot_a = await InventoryQuery.get_snapshot(session, snapshot_id_a, with_items=False)
    snapshot_b = await InventoryQuery.get_snapshot(session, snapshot_id_b, with_items=False)
    
    if not snapshot_a:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id_a} not found")
    if not snapshot_b:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id_b} not found")
    
    diff = await InventoryQuery.compare_snapshots(session, snapshot_id_a, snapshot_id_b)
    
    return {
        "snapshot_a": {
            "id": snapshot_a.id,
            "name": snapshot_a.name,
            "created_at": snapshot_a.created_at.isoformat(),
        },
        "snapshot_b": {
            "id": snapshot_b.id,
            "name": snapshot_b.name,
            "created_at": snapshot_b.created_at.isoformat(),
        },
        "differences": diff,
    }


@app.get("/inventory/current")
async def get_current_inventory(
    up_to_snapshot_id: Optional[int] = None,
    session: AsyncSession = Depends(get_db_session),
) -> dict[int, int]:
    """Get current inventory state.
    
    Args:
        up_to_snapshot_id: Only include snapshots up to this ID
        session: Database session
        
    Returns:
        Current inventory mapping item_id to quantity
    """
    return await InventoryQuery.get_current_inventory(session, up_to_snapshot_id)
