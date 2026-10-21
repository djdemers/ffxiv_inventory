"""Command line for the crafting companion.

    python -m companion.cli ask "What do I need to craft a Bronze Ingot?"
    python -m companion.cli chat
    python -m companion.cli tool get_recipe '{"item_name": "Bronze Ingot"}'
"""

import argparse
import json
import sys

from .tools import TOOL_FUNCTIONS, call_tool


def main() -> None:
    parser = argparse.ArgumentParser(description="FFXIV ARR crafting companion")
    sub = parser.add_subparsers(dest="cmd", required=True)
    ask = sub.add_parser("ask", help="ask one question")
    ask.add_argument("question")
    ask.add_argument("--show-tools", action="store_true", help="print the tool calls made")
    sub.add_parser("chat", help="interactive chat")
    tool = sub.add_parser("tool", help="call a lookup tool directly (no Claude, no API key)")
    tool.add_argument("name", choices=sorted(TOOL_FUNCTIONS))
    tool.add_argument("args", nargs="?", default="{}", help="JSON object of arguments")
    args = parser.parse_args()

    if args.cmd == "tool":
        print(json.dumps(call_tool(args.name, json.loads(args.args)), indent=2, ensure_ascii=False))
        return

    from .agent import Companion  # imported here so `tool` works without the SDK installed

    bot = Companion()
    if args.cmd == "ask":
        print(bot.ask(args.question))
        if args.show_tools:
            for call in bot.tool_log:
                print(f"  [tool] {call['name']} {json.dumps(call['input'])}", file=sys.stderr)
        return

    print("ARR crafting companion. Ctrl-D to quit.")
    while True:
        try:
            question = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if question:
            print("\n" + bot.ask(question))


if __name__ == "__main__":
    main()
