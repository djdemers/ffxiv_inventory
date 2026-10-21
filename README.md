# FFXIV crafting companion (ARR prototype)

A retrieval-augmented (RAG) assistant for A Realm Reborn crafting, levels 1-50. Claude answers
questions by calling lookup tools over a local copy of the game data, so recipes, levels, and
prices come from data rather than the model's memory. The same tools are meant to become the
API behind a crafting planner website.

## Quick start

```bash
pip install -r requirements.txt
python -m companion.build_db              # downloads game data CSVs, builds data/ffxiv_arr.db
export ANTHROPIC_API_KEY=sk-ant-...
python -m companion.cli ask "What do I need for 3 Iron Ingots as a Blacksmith?" --show-tools
python -m companion.cli chat
```

The tools work without an API key:

```bash
python -m companion.cli tool get_recipe '{"item_name": "Hi-Potion"}'
python -m companion.cli tool get_material_list '{"items": [{"name": "Bronze Hatchet", "quantity": 2}]}'
python -m companion.cli tool get_price '{"item_names": ["Cobalt Ore"], "world": "Aether"}'
```

## Crafting planner website

A local web page over the same tools. It needs no API key and nothing extra to install.

```bash
python -m companion.server        # then open http://localhost:8000
```

- **Browse by job:** pick a crafting job and level range to list recipes, with the levequests for that range.
- **Search:** find any craftable item by name.
- **Recipe details:** ingredients, and where each one comes from (crafted, gathered, or vendor price).
- **My plan:** add items with "+ Plan" to get one combined shopping list. Shared materials are merged, intermediates (ingots, lumber, yarn) are broken down, and the crafts are listed in the order you make them. Tick "Prefer recipes from" for the jobs you're leveling.
- **Prices:** enter a world or data center and press "Get prices" for Universalis market prices and an estimated total, using the cheaper of vendor and market for each material.

Your plan and checkboxes are saved in your browser.

## How it works

| Piece | File | What it does |
|---|---|---|
| Ingest | `companion/build_db.py` | Downloads 12 game-data sheets (Recipe, Item, Leve, ...) and keeps ARR-range crafting recipes, their items, and DoH levequests in SQLite. |
| Index | same | Writes one short text document per recipe, item, and leve into an SQLite FTS5 table (BM25 keyword search). |
| Tools | `companion/tools.py` | `search`, `get_recipe`, `get_item`, `list_recipes`, `find_leves`, `get_material_list`, `get_price`. Plain functions returning JSON. |
| Prices | `companion/market.py` | Universalis API client with a 15-minute SQLite cache. |
| Website | `companion/server.py`, `companion/web/index.html` | Standard-library HTTP server with a JSON API over the tools, and a single-page planner. |
| Assistant | `companion/agent.py` | Claude tool-use loop with a grounding system prompt. Model: `claude-opus-5-5` (override with `COMPANION_MODEL`). |
| Tests | `evals/`, `tests/` | 27 test questions, plus unit tests. |

Structured lookups (exact recipe, ingredient amounts) go through SQL tables. Search is only
for finding names and open-ended questions. For this kind of data that is more reliable than
vector search, and it needs no embedding service. If free-text guide content is added later,
an embedding index can sit next to FTS5 behind the same `search` tool.

`get_material_list` is the planner's core: it merges shared materials across several target
items, breaks intermediates (ingots, lumber, yarn) into raw materials, rounds up by recipe yield,
and lets you prefer recipes from the jobs you're leveling.

## Tests

```bash
python -m unittest discover tests     # tools, Universalis parsing (mocked), agent loop (stubbed)
python evals/run_evals.py             # 26 offline fact checks against the tools
python evals/run_evals.py --live      # also asks Claude every question (uses API credits)
```

Live mode checks each answer for expected facts. Two questions have only review notes (an
out-of-scope level 90 item, and a price question with no world given); read those by hand.

## Data sources and licensing

- **Game data:** CSVs from [xivapi/ffxiv-datamining](https://github.com/xivapi/ffxiv-datamining),
  the export the XIVAPI project maintains. Game data belongs to Square Enix, so check Square
  Enix's materials usage terms before running a public site. Run `python -m companion.build_db --refresh` after a patch.
- **Prices:** [Universalis](https://docs.universalis.app/) public API, cached to keep request rates low.
- **Not used:** Teamcraft and Garland Tools (no bulk reuse), and no wiki text yet. Check each
  wiki's license before indexing its text.

## Known gaps

- No gathering node locations, vendor locations, quest unlocks, or crafting rotations.
- A few later-patch recipes in the 1-50 range (furnishings, orchestrion rolls) are included; they
  carry a `patch` field.
- Recipe difficulty, durability, and quality are computed from the level table and may not match
  the in-game numbers exactly.
