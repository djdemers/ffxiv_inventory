"""Build the local ARR crafting database (SQLite + FTS5 search index).

Source: the game-data CSV export maintained by the XIVAPI project
(https://github.com/xivapi/ffxiv-datamining). CSVs are downloaded once into
data/raw/ and reused on later runs. Pass --refresh to download them again
after a game patch.

    python -m companion.build_db [--refresh]
"""

import argparse
import csv
import sqlite3
import sys
import urllib.request
from pathlib import Path

from .db import DB_PATH, ROOT

RAW_DIR = ROOT / "data" / "raw"
CSV_BASE = "https://raw.githubusercontent.com/xivapi/ffxiv-datamining/master/csv/en/"
SHEETS = [
    "Recipe", "RecipeLevelTable", "Item", "ItemUICategory", "GilShopItem",
    "GatheringItem", "GatheringItemLevelConvertTable", "CraftLeve", "Leve",
    "ClassJobCategory", "Town", "SecretRecipeBook",
]

# Recipe.CraftType index -> (abbreviation, job name)
CRAFT_JOBS = {
    0: ("CRP", "Carpenter"), 1: ("BSM", "Blacksmith"), 2: ("ARM", "Armorer"),
    3: ("GSM", "Goldsmith"), 4: ("LTW", "Leatherworker"), 5: ("WVR", "Weaver"),
    6: ("ALC", "Alchemist"), 7: ("CUL", "Culinarian"),
}
MAX_LEVEL = 50  # A Realm Reborn cap

SCHEMA = """
CREATE TABLE items (
    id INTEGER PRIMARY KEY, name TEXT, description TEXT, category TEXT,
    item_level INTEGER, can_hq INTEGER, untradable INTEGER,
    vendor_price INTEGER,          -- gil, only set when a gil shop sells it
    gather_level INTEGER, gather_stars INTEGER
);
CREATE INDEX items_name ON items(name COLLATE NOCASE);
CREATE TABLE recipes (
    id INTEGER PRIMARY KEY, item_id INTEGER, job TEXT, job_name TEXT,
    level INTEGER, stars INTEGER, yields INTEGER,
    durability INTEGER, difficulty INTEGER, quality INTEGER,
    req_craftsmanship INTEGER, req_control INTEGER,
    can_hq INTEGER, quick_synth INTEGER, master_book TEXT, patch TEXT
);
CREATE INDEX recipes_item ON recipes(item_id);
CREATE TABLE ingredients (
    recipe_id INTEGER, item_id INTEGER, amount INTEGER, is_crystal INTEGER
);
CREATE INDEX ingredients_recipe ON ingredients(recipe_id);
CREATE INDEX ingredients_item ON ingredients(item_id);
CREATE TABLE leves (
    id INTEGER PRIMARY KEY, name TEXT, job TEXT, level INTEGER,
    gil_reward INTEGER, town TEXT, item_id INTEGER, amount INTEGER, repeats INTEGER
);
CREATE TABLE price_cache (
    item_id INTEGER, scope TEXT, fetched_at REAL, payload TEXT,
    PRIMARY KEY (item_id, scope)
);
CREATE VIRTUAL TABLE docs USING fts5(
    kind UNINDEXED, ref_id UNINDEXED, title, body, tokenize = 'porter unicode61'
);
"""


def download(refresh: bool) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for sheet in SHEETS:
        path = RAW_DIR / f"{sheet}.csv"
        if path.exists() and not refresh:
            continue
        print(f"downloading {sheet}.csv")
        with urllib.request.urlopen(CSV_BASE + f"{sheet}.csv", timeout=60) as r:
            path.write_bytes(r.read())


def read_sheet(sheet: str) -> list[dict]:
    with open(RAW_DIR / f"{sheet}.csv", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def as_int(value: str) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def build() -> None:
    items = {as_int(r["#"]): r for r in read_sheet("Item")}
    ui_categories = {as_int(r["#"]): r["Name"] for r in read_sheet("ItemUICategory")}
    level_table = {as_int(r["#"]): r for r in read_sheet("RecipeLevelTable")}
    books = {as_int(r["#"]): r["Name"] for r in read_sheet("SecretRecipeBook")}
    sold = {as_int(r["Item"]) for r in read_sheet("GilShopItem")}
    gather_levels = {as_int(r["#"]): r for r in read_sheet("GatheringItemLevelConvertTable")}
    gathered = {}
    for r in read_sheet("GatheringItem"):
        item_id, lvl = as_int(r["Item"]), gather_levels.get(as_int(r["GatheringItemLevel"]))
        if item_id in items and lvl and as_int(lvl["GatheringItemLevel"]) > 0:
            level = as_int(lvl["GatheringItemLevel"])
            if item_id not in gathered or level < gathered[item_id][0]:
                gathered[item_id] = (level, as_int(lvl["Stars"]))

    # Keep ARR-range recipes, and every item they make or use.
    recipes, ingredients, used = [], [], set()
    for r in read_sheet("Recipe"):
        result = as_int(r["ItemResult"])
        lvl = level_table.get(as_int(r["RecipeLevelTable"]))
        craft = as_int(r["CraftType"])
        if result <= 0 or not lvl or craft not in CRAFT_JOBS:
            continue
        level = as_int(lvl["ClassJobLevel"])
        if not 1 <= level <= MAX_LEVEL or r.get("IsExpert") == "True":
            continue
        if as_int(r["StatusRequired"]) > 0:  # event/status-locked crafts (e.g. airship parts)
            continue
        rid = as_int(r["#"])
        job, job_name = CRAFT_JOBS[craft]
        patch = as_int(r["PatchNumber"])
        recipes.append((
            rid, result, job, job_name, level, as_int(lvl["Stars"]), as_int(r["AmountResult"]),
            as_int(lvl["Durability"]) * as_int(r["DurabilityFactor"]) // 100,
            as_int(lvl["Difficulty"]) * as_int(r["DifficultyFactor"]) // 100,
            as_int(lvl["Quality"]) * as_int(r["QualityFactor"]) // 100,
            as_int(r["RequiredCraftsmanship"]), as_int(r["RequiredControl"]),
            r["CanHq"] == "True", r["CanQuickSynth"] == "True",
            books.get(as_int(r["SecretRecipeBook"])) or None,
            f"{patch // 100}.{patch % 100}" if patch else None,
        ))
        used.add(result)
        for i in range(8):
            ing, amount = as_int(r[f"Ingredient[{i}]"]), as_int(r[f"AmountIngredient[{i}]"])
            if ing > 0 and amount > 0 and ing in items:
                ingredients.append((rid, ing, amount, i >= 6))
                used.add(ing)

    # Levequests for DoH jobs, level 1-50.
    jobs_by_abbr = {abbr for abbr, _ in CRAFT_JOBS.values()}
    categories = {as_int(r["#"]): r for r in read_sheet("ClassJobCategory")}
    towns = {as_int(r["#"]): r["Name"] for r in read_sheet("Town")}
    leve_rows = {as_int(r["#"]): r for r in read_sheet("Leve")}
    leves = []
    for r in read_sheet("CraftLeve"):
        leve = leve_rows.get(as_int(r["Leve"]))
        item_id = as_int(r["Item[0]"])
        if not leve or not leve["Name"] or item_id not in items:
            continue
        category = categories.get(as_int(leve["ClassJobCategory"]), {})
        job = next((a for a in jobs_by_abbr if category.get(a) == "True"), None)
        level = as_int(leve["ClassJobLevel"])
        if not job or not 1 <= level <= MAX_LEVEL:
            continue
        leves.append((
            as_int(leve["#"]), leve["Name"], job, level, as_int(leve["GilReward"]),
            towns.get(as_int(leve["Town"])), item_id, as_int(r["ItemCount[0]"]), as_int(r["Repeats"]),
        ))
        used.add(item_id)

    if DB_PATH.exists():
        DB_PATH.unlink()
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    item_rows = []
    for item_id in sorted(used):
        it = items[item_id]
        gather = gathered.get(item_id, (None, None))
        item_rows.append((
            item_id, it["Name"], it["Description"].replace("\n", " "),
            ui_categories.get(as_int(it["ItemUICategory"])), as_int(it["LevelItem"]),
            it["CanBeHq"] == "True", it["IsUntradable"] == "True",
            as_int(it["PriceMid"]) if item_id in sold else None, gather[0], gather[1],
        ))
    con.executemany("INSERT INTO items VALUES (?,?,?,?,?,?,?,?,?,?)", item_rows)
    con.executemany("INSERT INTO recipes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", recipes)
    con.executemany("INSERT INTO ingredients VALUES (?,?,?,?)", ingredients)
    con.executemany("INSERT INTO leves VALUES (?,?,?,?,?,?,?,?,?)", leves)
    index_docs(con)
    con.commit()
    counts = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
              for t in ("items", "recipes", "ingredients", "leves", "docs")}
    con.close()
    print(f"built {DB_PATH.relative_to(ROOT)}: {counts}")


def index_docs(con: sqlite3.Connection) -> None:
    """Write one plain-text search document per recipe, item, and leve."""
    name = dict(con.execute("SELECT id, name FROM items"))
    ings = {}
    for rid, iid, amount, crystal in con.execute("SELECT * FROM ingredients"):
        ings.setdefault(rid, []).append(f"{amount}x {name[iid]}")
    docs = []
    for r in con.execute(
        "SELECT r.id, r.item_id, r.job, r.job_name, r.level, r.stars, r.yields, r.can_hq, "
        "r.master_book, i.category FROM recipes r JOIN items i ON i.id = r.item_id"
    ):
        rid, iid, job, job_name, level, stars, yields, can_hq, book, category = r
        stars_txt = "★" * stars
        body = (f"{job_name} ({job}) level {level}{stars_txt} recipe. Category: {category}. "
                f"Yields {yields}. Ingredients: {', '.join(ings.get(rid, []))}."
                + (" Can be HQ." if can_hq else "")
                + (f" Requires master recipe book {book}." if book else ""))
        docs.append(("recipe", rid, name[iid], body))
    for iid, nm, desc, category, vendor, glvl in con.execute(
        "SELECT id, name, description, category, vendor_price, gather_level FROM items"
    ):
        sources = []
        if glvl:
            sources.append(f"gatherable at level {glvl}")
        if vendor:
            sources.append(f"sold by vendors for {vendor} gil")
        crafted = con.execute("SELECT job, level FROM recipes WHERE item_id = ?", (iid,)).fetchall()
        sources += [f"crafted by {j} level {l}" for j, l in crafted]
        uses = con.execute(
            "SELECT DISTINCT it.name FROM ingredients g JOIN recipes r ON r.id = g.recipe_id "
            "JOIN items it ON it.id = r.item_id WHERE g.item_id = ? LIMIT 12", (iid,)
        ).fetchall()
        body = (f"{category or 'Item'}. {desc} Sources: {', '.join(sources) or 'unknown'}."
                + (f" Used in: {', '.join(u for (u,) in uses)}." if uses else ""))
        docs.append(("item", iid, nm, body))
    for lid, nm, job, level, gil, town, iid, amount, repeats in con.execute("SELECT * FROM leves"):
        body = (f"{job} levequest, level {level}, issued in {town}. Turn in {amount}x {name[iid]}"
                + (f" (repeatable {repeats} more times)" if repeats else "")
                + f". Reward: {gil} gil plus experience.")
        docs.append(("leve", lid, nm, body))
    con.executemany("INSERT INTO docs (kind, ref_id, title, body) VALUES (?,?,?,?)", docs)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="re-download the CSVs")
    args = parser.parse_args()
    try:
        download(args.refresh)
    except OSError as exc:
        sys.exit(f"could not download game data: {exc}")
    build()


if __name__ == "__main__":
    main()
