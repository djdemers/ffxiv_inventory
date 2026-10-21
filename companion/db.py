import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "ffxiv_arr.db"


def connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"{DB_PATH} not found; run: python -m companion.build_db")
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con
