"""Exercise the planner's JSON API through a real local HTTP server."""

import json
import threading
import unittest
import urllib.request
from http.server import HTTPServer

from companion.server import Handler


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as r:
            return r.status, r.read()

    def test_page_is_served(self):
        status, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Crafting planner", body)

    def test_recipes_endpoint(self):
        _, body = self.get("/api/recipes?job=CUL&min=1&max=3")
        self.assertIn("Boiled Egg", [r["name"] for r in json.loads(body)["recipes"]])

    def test_materials_endpoint(self):
        req = urllib.request.Request(self.base + "/api/materials", method="POST",
                                     data=json.dumps({"items": [{"name": "Iron Ingot", "quantity": 3}],
                                                      "prefer_jobs": ["BSM"]}).encode())
        with urllib.request.urlopen(req) as r:
            data = json.loads(r.read())
        raw = {m["name"]: m["quantity"] for m in data["raw_materials"]}
        self.assertEqual(raw["Iron Ore"], 9)
        self.assertIn("Fire Shard", raw)

    def test_bad_job_is_400(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/api/recipes?job=Paladin")
        self.assertEqual(ctx.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
