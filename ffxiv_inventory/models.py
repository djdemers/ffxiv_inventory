"""Database models for FFXIV inventory tracking."""

from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, Index, String, Integer, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all database models."""
    pass


class Snapshot(Base):
    """Immutable snapshot of inventory at a point in time."""
    
    __tablename__ = "snapshots"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # Relationship to items in this snapshot
    items: Mapped[list["SnapshotItem"]] = relationship(
        "SnapshotItem",
        back_populates="snapshot",
        cascade="all, delete-orphan"
    )
    
    def __repr__(self) -> str:
        return f"<Snapshot(id={self.id}, created_at={self.created_at}, name={self.name})>"


class SnapshotItem(Base):
    """Item within a snapshot - immutable record of item and quantity."""
    
    __tablename__ = "snapshot_items"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(
        Integer, 
        ForeignKey("snapshots.id", ondelete="CASCADE"),
        nullable=False
    )
    item_id: Mapped[int] = mapped_column(Integer, nullable=False)  # XIVAPI item ID
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    
    # Relationships
    snapshot: Mapped["Snapshot"] = relationship("Snapshot", back_populates="items")
    item_info: Mapped[Optional["ItemInfo"]] = relationship(
        "ItemInfo",
        foreign_keys=[item_id],
        primaryjoin="SnapshotItem.item_id == ItemInfo.item_id",
        viewonly=True
    )
    
    # Index for efficient querying
    __table_args__ = (
        Index("idx_snapshot_item", "snapshot_id", "item_id"),
    )
    
    def __repr__(self) -> str:
        return f"<SnapshotItem(id={self.id}, item_id={self.item_id}, quantity={self.quantity})>"


class ItemInfo(Base):
    """Cached item information from XIVAPI."""
    
    __tablename__ = "item_info"
    
    item_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    icon_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    item_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime, 
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )
    
    def __repr__(self) -> str:
        return f"<ItemInfo(item_id={self.item_id}, name={self.name})>"
