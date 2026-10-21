"""Unit tests for the lookup tools and the Universalis client (no network needed).

    python -m unittest discover tests
"""

import json
import sqlite3
import unittest
from unittest import mock

from companion import market, tools


class ToolTests(unittest.TestCase):
    def test_recipe_lists_ingredient_sources(self):
        recipe = tools.get_recipe("bronze ingot", "Blacksmith")["recipes"][0]
        ore = next(i for i in recipe["ingredients"] if i["name"] == "Copper Ore")
        self.assertEqual(ore["amount"], 2)
        self.assertEqual(ore["gather_level"], 1)
        self.assertTrue(ore["vendor_price"])

    def test_fuzzy_match_is_flagged(self):
        self.assertIn("note", tools.get_recipe("Cotton Cloth"))
        self.assertNotIn("note", tools.get_recipe("Undyed Cotton Cloth"))

    def test_unknown_job_is_an_error_not_a_crash(self):
        self.assertIn("error", tools.call_tool("list_recipes", {"job": "Paladin"}))

    def test_material_list_expands_and_merges(self):
        result = tools.get_material_list([{"name": "Bronze Ingot", "quantity": 2},
                                          {"name": "Bronze Ingot", "quantity": 1}], prefer_jobs=["BSM"])
        raw = {r["name"]: r["quantity"] for r in result["raw_materials"]}
        self.assertEqual(raw["Copper Ore"], 6)
        self.assertEqual(raw["Fire Shard"], 3)

    def test_material_list_rounds_up_by_yield(self):
        # Cotton Yarn yields 2 per synth, so 3 yarn takes 2 synths = 4 bolls.
        raw = {r["name"]: r["quantity"] for r in
               tools.get_material_list([{"name": "Cotton Yarn", "quantity": 3}])["raw_materials"]}
        self.assertEqual(raw["Cotton Boll"], 4)

    def test_search_ranks_title_matches_first(self):
        self.assertEqual(tools.search("hi-potion")["results"][0]["title"], "Hi-Potion")

    def test_schemas_match_functions(self):
        self.assertEqual({s["name"] for s in tools.TOOL_SCHEMAS}, set(tools.TOOL_FUNCTIONS))


class MarketTests(unittest.TestCase):
    SAMPLE = {"items": {"5106": {
        "itemID": 5106, "minPriceNQ": 40, "minPriceHQ": 0, "averagePriceNQ": 52.4,
        "averagePriceHQ": 0, "regularSaleVelocity": 31.25, "lastUploadTime": 1760000000000,
        "listings": [{"worldName": "Gilgamesh", "pricePerUnit": 40}],
    }, "5107": {
        "itemID": 5107, "minPriceNQ": 12, "minPriceHQ": 0, "averagePriceNQ": 15,
        "regularSaleVelocity": 4, "lastUploadTime": 1760000000000, "listings": [],
    }}}

    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.execute("CREATE TABLE price_cache (item_id INTEGER, scope TEXT, fetched_at REAL, "
                         "payload TEXT, PRIMARY KEY (item_id, scope))")

    def fake_urlopen(self, payload):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
        return mock.patch("urllib.request.urlopen", return_value=response)

    def test_parses_and_caches(self):
        with self.fake_urlopen(self.SAMPLE) as urlopen:
            prices = market.get_prices(self.con, [5106, 5107], "Aether")
            again = market.get_prices(self.con, [5106], "aether")
        self.assertEqual(urlopen.call_count, 1)  # second call served from cache
        self.assertEqual(prices[5106]["min_price_nq"], 40)
        self.assertIsNone(prices[5106]["min_price_hq"])
        self.assertEqual(prices[5106]["cheapest_world"], "Gilgamesh")
        self.assertEqual(again[5106]["average_sale_nq"], 52)

    def test_single_item_response_shape(self):
        with self.fake_urlopen(self.SAMPLE["items"]["5107"]):
            prices = market.get_prices(self.con, [5107], "Gilgamesh")
        self.assertEqual(prices[5107]["min_price_nq"], 12)


if __name__ == "__main__":
    unittest.main()
