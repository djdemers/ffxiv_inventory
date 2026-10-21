"""Lookup tools over the local ARR crafting database.

Each public function takes plain JSON-able arguments and returns a JSON-able
dict, so the same functions back the Claude assistant and, later, a website API.
"""

import re
import sqlite3
from collections import defaultdict

from . import market
from .db import connect

JOBS = {"CRP", "BSM", "ARM", "GSM", "LTW", "WVR", "ALC", "CUL"}
JOB_ALIASES = {
    "carpenter": "CRP", "blacksmith": "BSM", "armorer": "ARM", "armourer": "ARM",
    "goldsmith": "GSM", "leatherworker": "LTW", "weaver": "WVR", "alchemist": "ALC",
    "culinarian": "CUL", "cook": "CUL",
}

_con: sqlite3.Connection | None = None


def _db() -> sqlite3.Connection:
    global _con
    if _con is None:
        _con = connect()
    return _con


def normalize_job(job: str | None) -> str | None:
    if not job:
        return None
    key = job.strip().lower()
    abbr = JOB_ALIASES.get(key, key.upper())
    if abbr not in JOBS:
        raise ValueError(f"unknown crafting job {job!r}; use one of {sorted(JOBS)}")
    return abbr


STOPWORDS = set(
    "a an and are at be by can do does for from get how i in is it make me my need "
    "of on or the to use uses used what where which who why with you".split()
)


def _fts_query(text: str) -> str:
    words = [w for w in re.findall(r"\w+", text.lower()) if w not in STOPWORDS]
    return " OR ".join(f'"{w}"' for w in words)


def search(query: str, kind: str | None = None, limit: int = 8) -> dict:
    """Full-text (BM25) search over recipe, item, and levequest documents."""
    fts = _fts_query(query)
    if not fts:
        return {"results": []}
    sql = "SELECT kind, ref_id, title, body FROM docs WHERE docs MATCH ?"
    args: list = [fts]
    if kind:
        sql += " AND kind = ?"
        args.append(kind)
    # Weight title matches well above body matches.
    sql += " ORDER BY bm25(docs, 0, 0, 10.0, 1.0) LIMIT ?"
    args.append(max(1, min(limit, 25)))
    rows = _db().execute(sql, args).fetchall()
    return {"results": [dict(r) for r in rows]}


def find_item(name: str) -> sqlite3.Row | None:
    """Resolve an item by exact name, then by best search match."""
    con = _db()
    row = con.execute("SELECT * FROM items WHERE name = ? COLLATE NOCASE", (name.strip(),)).fetchone()
    if row:
        return row
    hits = search(name, kind="item", limit=1)["results"]
    if hits:
        return con.execute("SELECT * FROM items WHERE id = ?", (hits[0]["ref_id"],)).fetchone()
    return None


def _match_note(query: str, item: sqlite3.Row) -> dict:
    """Flag fuzzy matches so the model doesn't present the wrong item as exact."""
    if item["name"].lower() == query.strip().lower():
        return {}
    return {"note": f"no item named {query!r}; showing closest match {item['name']!r}"}


def _sources(item: sqlite3.Row) -> dict:
    con = _db()
    crafted = con.execute("SELECT id, job, level, stars FROM recipes WHERE item_id = ?", (item["id"],))
    return {
        "crafted_by": [dict(r) for r in crafted],
        "gather_level": item["gather_level"],
        "vendor_price": item["vendor_price"],
        "tradable_on_market": not item["untradable"],
    }


def get_item(name: str) -> dict:
    """Item details: category, how to obtain it, and which ARR recipes use it."""
    item = find_item(name)
    if not item:
        return {"error": f"no item matching {name!r} in the ARR crafting data"}
    uses = _db().execute(
        "SELECT r.id AS recipe_id, it.name AS makes, r.job, r.level, g.amount "
        "FROM ingredients g JOIN recipes r ON r.id = g.recipe_id JOIN items it ON it.id = r.item_id "
        "WHERE g.item_id = ? ORDER BY r.level LIMIT 40", (item["id"],)
    ).fetchall()
    return {
        **_match_note(name, item),
        "id": item["id"], "name": item["name"], "category": item["category"],
        "description": item["description"], "can_hq": bool(item["can_hq"]),
        **_sources(item), "used_in": [dict(u) for u in uses],
    }


def _recipe_detail(recipe: sqlite3.Row) -> dict:
    con = _db()
    item = con.execute("SELECT * FROM items WHERE id = ?", (recipe["item_id"],)).fetchone()
    ingredients = []
    for g in con.execute(
        "SELECT g.amount, g.is_crystal, i.* FROM ingredients g JOIN items i ON i.id = g.item_id "
        "WHERE g.recipe_id = ?", (recipe["id"],)
    ):
        ingredients.append({"item_id": g["id"], "name": g["name"], "amount": g["amount"],
                            "is_crystal": bool(g["is_crystal"]), **_sources(g)})
    detail = {k: recipe[k] for k in recipe.keys()}
    detail.update(item_name=item["name"], category=item["category"],
                  can_hq=bool(recipe["can_hq"]), quick_synth=bool(recipe["quick_synth"]),
                  ingredients=ingredients)
    return detail


def get_recipe(item_name: str, job: str | None = None) -> dict:
    """Recipe(s) that craft an item, with ingredients and where to get each one."""
    item = find_item(item_name)
    if not item:
        return {"error": f"no item matching {item_name!r} in the ARR crafting data"}
    sql, args = "SELECT * FROM recipes WHERE item_id = ?", [item["id"]]
    if job:
        sql += " AND job = ?"
        args.append(normalize_job(job))
    recipes = _db().execute(sql + " ORDER BY level", args).fetchall()
    if not recipes:
        return {"item": item["name"], **_match_note(item_name, item),
                "error": "this item has no level 1-50 crafting recipe" + (f" for {job}" if job else ""),
                **_sources(item)}
    return {"item": item["name"], **_match_note(item_name, item),
            "recipes": [_recipe_detail(r) for r in recipes]}


def list_recipes(job: str, min_level: int = 1, max_level: int = 50, limit: int = 60) -> dict:
    """Recipes for a job within a level range, lowest level first."""
    abbr = normalize_job(job)
    rows = _db().execute(
        "SELECT r.id, i.name, r.level, r.stars, i.category, r.yields FROM recipes r "
        "JOIN items i ON i.id = r.item_id WHERE r.job = ? AND r.level BETWEEN ? AND ? "
        "ORDER BY r.level, r.stars, i.name LIMIT ?", (abbr, min_level, max_level, min(limit, 200))
    ).fetchall()
    return {"job": abbr, "recipes": [dict(r) for r in rows]}


def find_leves(job: str, min_level: int = 1, max_level: int = 50) -> dict:
    """Crafting levequests for a job within a level range."""
    abbr = normalize_job(job)
    rows = _db().execute(
        "SELECT l.name, l.level, l.town, l.gil_reward, i.name AS turn_in, l.amount, l.repeats "
        "FROM leves l JOIN items i ON i.id = l.item_id WHERE l.job = ? AND l.level BETWEEN ? AND ? "
        "ORDER BY l.level, l.name", (abbr, min_level, max_level)
    ).fetchall()
    return {"job": abbr, "leves": [dict(r) for r in rows]}


def get_material_list(items: list[dict], expand_intermediates: bool = True,
                      prefer_jobs: list[str] | None = None) -> dict:
    """Total shopping list for crafting several items.

    items: [{"name": "Bronze Ingot", "quantity": 3}, ...]. With
    expand_intermediates, craftable ingredients are broken down into their own
    ingredients, so the result lists only raw materials plus the intermediate
    crafts you will make along the way. When an item has recipes on several
    jobs, a job in prefer_jobs wins; otherwise the lowest-level recipe is used.
    """
    preferred = [normalize_job(j) for j in prefer_jobs or []]
    raw: dict[int, int] = defaultdict(int)
    crafts: dict[int, int] = defaultdict(int)
    missing: list[str] = []
    con = _db()

    def lowest_recipe(item_id: int):
        rows = con.execute("SELECT * FROM recipes WHERE item_id = ? ORDER BY level", (item_id,)).fetchall()
        for job in preferred:
            for row in rows:
                if row["job"] == job:
                    return row
        return rows[0] if rows else None

    def add(item_id: int, qty: int, top: bool, depth: int = 0) -> None:
        recipe = lowest_recipe(item_id)
        if recipe is None or depth > 8 or (not top and not expand_intermediates):
            raw[item_id] += qty
            return
        crafts[item_id] += qty
        runs = -(-qty // recipe["yields"])  # ceil
        for g in con.execute("SELECT item_id, amount FROM ingredients WHERE recipe_id = ?", (recipe["id"],)):
            add(g["item_id"], g["amount"] * runs, False, depth + 1)

    for entry in items:
        item = find_item(entry["name"])
        if not item:
            missing.append(entry["name"])
            continue
        add(item["id"], int(entry.get("quantity", 1)), True)

    def describe(item_id: int, qty: int) -> dict:
        it = con.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        row = {"name": it["name"], "quantity": qty, "gather_level": it["gather_level"],
               "vendor_price": it["vendor_price"]}
        if it["vendor_price"]:
            row["vendor_total"] = it["vendor_price"] * qty
        return row

    result = {
        "crafts": [describe(i, q) | {"job": lowest_recipe(i)["job"], "level": lowest_recipe(i)["level"]}
                   for i, q in crafts.items()],
        "raw_materials": sorted((describe(i, q) for i, q in raw.items()), key=lambda r: r["name"]),
    }
    if missing:
        result["not_found"] = missing
    return result


def get_price(item_names: list[str], world: str) -> dict:
    """Live market board prices from Universalis for a world, data center, or region."""
    resolved, missing = {}, []
    for name in item_names[:20]:
        item = find_item(name)
        if item and not item["untradable"]:
            resolved[item["id"]] = item["name"]
        else:
            missing.append(name)
    if not resolved:
        return {"error": "no tradable items matched", "not_found": missing}
    try:
        prices = market.get_prices(_db(), list(resolved), world)
    except market.MarketError as exc:
        return {"error": str(exc), "items": list(resolved.values())}
    out = {"world": world, "source": "universalis.app",
           "prices": [{"name": resolved[i], **p} for i, p in prices.items()]}
    if missing:
        out["not_found_or_untradable"] = missing
    return out


TOOL_FUNCTIONS = {
    "search": search,
    "get_item": get_item,
    "get_recipe": get_recipe,
    "list_recipes": list_recipes,
    "find_leves": find_leves,
    "get_material_list": get_material_list,
    "get_price": get_price,
}

JOB_ENUM = sorted(JOBS)
TOOL_SCHEMAS = [
    {
        "name": "search",
        "description": "Keyword search over A Realm Reborn (level 1-50) crafting data: recipes, items "
                       "(materials, gear, food), and crafting levequests. Use it to find names when you "
                       "are unsure of the exact item, or to answer open questions such as 'what uses "
                       "cotton'. Returns short text documents with ids.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keywords, e.g. 'bronze ingot' or 'weaver cotton'."},
                "kind": {"type": "string", "enum": ["recipe", "item", "leve"],
                         "description": "Optional filter by document type."},
                "limit": {"type": "integer", "description": "Max results, default 8."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_recipe",
        "description": "Get the exact crafting recipe for an item: job, level, stars, yield, ingredients "
                       "with amounts, and for each ingredient whether it is crafted, gathered (and at "
                       "what level), or sold by vendors (and for how much gil).",
        "input_schema": {
            "type": "object",
            "properties": {
                "item_name": {"type": "string", "description": "The crafted item's name."},
                "job": {"type": "string", "enum": JOB_ENUM, "description": "Optional crafting job filter."},
            },
            "required": ["item_name"],
        },
    },
    {
        "name": "get_item",
        "description": "Get an item's category and description, how to obtain it (crafted, gathered, "
                       "vendor), whether it can be traded on the market board, and which recipes use it.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "list_recipes",
        "description": "List a crafting job's recipes within a level range, lowest level first. Use for "
                       "leveling plans ('what can a level 12 weaver make').",
        "input_schema": {
            "type": "object",
            "properties": {
                "job": {"type": "string", "enum": JOB_ENUM},
                "min_level": {"type": "integer"},
                "max_level": {"type": "integer"},
                "limit": {"type": "integer", "description": "Max rows, default 60."},
            },
            "required": ["job"],
        },
    },
    {
        "name": "find_leves",
        "description": "List crafting levequests for a job within a level range: name, level, issuing "
                       "town, gil reward, and the item and count to turn in.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job": {"type": "string", "enum": JOB_ENUM},
                "min_level": {"type": "integer"},
                "max_level": {"type": "integer"},
            },
            "required": ["job"],
        },
    },
    {
        "name": "get_material_list",
        "description": "Compute the combined shopping list for crafting one or more items, merging shared "
                       "materials. By default breaks intermediate crafts (ingots, lumber, cloth) down into "
                       "raw materials, and lists the intermediate crafts separately. Pass prefer_jobs "
                       "when the user levels specific jobs, so shared intermediates use those recipes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}, "quantity": {"type": "integer"}},
                        "required": ["name"],
                    },
                },
                "expand_intermediates": {"type": "boolean"},
                "prefer_jobs": {"type": "array", "items": {"type": "string", "enum": JOB_ENUM}},
            },
            "required": ["items"],
        },
    },
    {
        "name": "get_price",
        "description": "Live market board prices from Universalis: cheapest current listing (NQ and HQ), "
                       "recent average sale price, and sales per day. Requires a world, data center, or "
                       "region name (e.g. 'Gilgamesh', 'Aether', 'North-America'). Ask the user for "
                       "their world or data center if you don't know it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item_names": {"type": "array", "items": {"type": "string"}, "description": "Up to 20 items."},
                "world": {"type": "string"},
            },
            "required": ["item_names", "world"],
        },
    },
]


def call_tool(name: str, args: dict) -> dict:
    func = TOOL_FUNCTIONS.get(name)
    if func is None:
        return {"error": f"unknown tool {name}"}
    try:
        return func(**args)
    except (TypeError, ValueError) as exc:
        return {"error": str(exc)}
