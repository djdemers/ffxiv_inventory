"""Claude assistant that answers ARR crafting questions using the lookup tools."""

import json
import os

import anthropic

from .tools import TOOL_SCHEMAS, call_tool

MODEL = os.environ.get("COMPANION_MODEL", "claude-opus-5-5")
MAX_TOOL_ROUNDS = 12

SYSTEM_PROMPT = """You are an FFXIV crafting companion for A Realm Reborn content (Disciples of the \
Hand, levels 1-50).

Answer from the tool results, not from memory: game data changes between patches, and the tools \
read the current game files and live market board. Look up every recipe, ingredient, level, and \
price you mention. If the tools don't have something (for example content above level 50, or a \
world's prices when Universalis is unreachable), say so plainly instead of guessing.

The data covers recipes, items and how to obtain them (crafted, gathered with the gathering level, \
or sold by vendors with the gil price), crafting levequests, and Universalis market prices. It \
does not include gathering node locations, vendor locations, or quest text, so for those point \
the user to an in-game source or a wiki rather than inventing details.

For prices, ask which world or data center the user plays on if they haven't said. Keep answers \
short and practical: lead with the answer, then a compact list of materials or steps."""


class Companion:
    def __init__(self, client: anthropic.Anthropic | None = None, model: str = MODEL):
        self.client = client or anthropic.Anthropic()
        self.model = model
        self.messages: list[dict] = []
        self.tool_log: list[dict] = []  # every tool call made, for evals and debugging

    def ask(self, question: str) -> str:
        self.messages.append({"role": "user", "content": question})
        for _ in range(MAX_TOOL_ROUNDS):
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                tools=TOOL_SCHEMAS,
                messages=self.messages,
                thinking={"type": "adaptive"},
                output_config={"effort": "medium"},
                # On a safety decline, retry on a fallback model chosen by the API.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "refusal":
                return "Sorry, I can't help with that request."
            if response.stop_reason == "pause_turn":
                continue
            if response.stop_reason != "tool_use":
                return "".join(b.text for b in response.content if b.type == "text").strip()

            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                output = call_tool(block.name, dict(block.input))
                self.tool_log.append({"name": block.name, "input": dict(block.input)})
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(output, ensure_ascii=False),
                    "is_error": "error" in output,
                })
            self.messages.append({"role": "user", "content": results})
        return "I stopped after too many lookups without reaching an answer. Try a narrower question."
