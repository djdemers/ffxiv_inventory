"""Local web server for the crafting planner.

Serves the planner page and a small JSON API over the lookup tools. Uses only
the standard library, so nothing extra to install.

    python -m companion.server            # then open http://localhost:8000
    python -m companion.server --port 9000
"""

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import tools

WEB_DIR = Path(__file__).resolve().parent / "web"
STATIC = {"/": ("index.html", "text/html; charset=utf-8")}


def _int(params: dict, key: str, default: int) -> int:
    try:
        return int(params.get(key, [default])[0])
    except ValueError:
        return default


def _str(params: dict, key: str, default: str | None = None) -> str | None:
    value = params.get(key, [default])[0]
    return value.strip() if isinstance(value, str) and value.strip() else default


def handle_get(path: str, params: dict) -> dict:
    if path == "/api/search":
        return tools.search(_str(params, "q", ""), kind=_str(params, "kind"), limit=_int(params, "limit", 10))
    if path == "/api/recipe":
        return tools.get_recipe(_str(params, "item", ""), job=_str(params, "job"))
    if path == "/api/item":
        return tools.get_item(_str(params, "name", ""))
    if path == "/api/recipes":
        return tools.list_recipes(_str(params, "job", ""), _int(params, "min", 1), _int(params, "max", 50),
                                  limit=_int(params, "limit", 200))
    if path == "/api/leves":
        return tools.find_leves(_str(params, "job", ""), _int(params, "min", 1), _int(params, "max", 50))
    if path == "/api/price":
        names = [n for n in (_str(params, "items", "") or "").split("|") if n]
        return tools.get_price(names, _str(params, "world", ""))
    raise LookupError(path)


def handle_post(path: str, body: dict) -> dict:
    if path == "/api/materials":
        return tools.get_material_list(body.get("items", []), body.get("expand_intermediates", True),
                                       body.get("prefer_jobs") or None)
    raise LookupError(path)


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, status: int, data: dict) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode(), "application/json")

    def _api(self, func, *args) -> None:
        try:
            self._json(200, func(*args))
        except LookupError:
            self._json(404, {"error": "not found"})
        except (TypeError, ValueError, KeyError) as exc:
            self._json(400, {"error": str(exc)})

    def do_GET(self) -> None:
        url = urlparse(self.path)
        if url.path in STATIC:
            name, content_type = STATIC[url.path]
            self._send(200, (WEB_DIR / name).read_bytes(), content_type)
        elif url.path.startswith("/api/"):
            self._api(handle_get, url.path, parse_qs(url.query))
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid JSON"})
            return
        self._api(handle_post, urlparse(self.path).path, body)

    def log_message(self, fmt: str, *args) -> None:
        pass  # keep the terminal quiet


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the crafting planner website locally")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    tools.search("warmup")  # fail fast if the database hasn't been built
    server = HTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Crafting planner running at http://localhost:{args.port}  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
