"""Universalis market board client with a small SQLite cache.

API docs: https://docs.universalis.app/ . Universalis asks clients to keep
request rates low, so results are cached for CACHE_SECONDS per item and world.
"""

import json
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://universalis.app/api/v2/{scope}/{ids}?listings=5&entries=5"
CACHE_SECONDS = 15 * 60
USER_AGENT = "ffxiv-crafting-rag-prototype/0.1"


class MarketError(Exception):
    pass


def _summarize(entry: dict) -> dict:
    listings = entry.get("listings") or []
    return {
        "min_price_nq": entry.get("minPriceNQ") or None,
        "min_price_hq": entry.get("minPriceHQ") or None,
        "average_sale_nq": round(entry["averagePriceNQ"]) if entry.get("averagePriceNQ") else None,
        "average_sale_hq": round(entry["averagePriceHQ"]) if entry.get("averagePriceHQ") else None,
        "sales_per_day": round(entry.get("regularSaleVelocity") or 0, 1),
        "listing_count": len(listings),
        "cheapest_world": listings[0].get("worldName") if listings else None,
        "last_upload": time.strftime("%Y-%m-%d %H:%M UTC",
                                     time.gmtime((entry.get("lastUploadTime") or 0) / 1000)),
    }


def fetch(item_ids: list[int], scope: str) -> dict[int, dict]:
    url = API.format(scope=urllib.parse.quote(scope), ids=",".join(map(str, item_ids)))
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.load(r)
    except urllib.error.HTTPError as exc:
        raise MarketError(f"Universalis returned HTTP {exc.code} for {scope!r}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise MarketError(f"could not reach Universalis: {exc}") from exc
    # One id returns the entry itself; several ids return {"items": {id: entry}}.
    entries = data.get("items") or {str(data.get("itemID")): data}
    return {int(k): _summarize(v) for k, v in entries.items() if v}


def get_prices(con: sqlite3.Connection, item_ids: list[int], scope: str) -> dict[int, dict]:
    scope_key = scope.strip().lower()
    now = time.time()
    out, stale = {}, []
    for item_id in item_ids:
        row = con.execute("SELECT fetched_at, payload FROM price_cache WHERE item_id = ? AND scope = ?",
                          (item_id, scope_key)).fetchone()
        if row and now - row[0] < CACHE_SECONDS:
            out[item_id] = json.loads(row[1])
        else:
            stale.append(item_id)
    if stale:
        fresh = fetch(stale, scope)
        for item_id, summary in fresh.items():
            con.execute("INSERT OR REPLACE INTO price_cache VALUES (?,?,?,?)",
                        (item_id, scope_key, now, json.dumps(summary)))
            out[item_id] = summary
        con.commit()
    return out
