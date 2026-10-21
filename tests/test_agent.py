"""Exercise the assistant's tool loop with a stubbed Claude client (no API key needed)."""

import unittest
from types import SimpleNamespace as NS
from unittest import mock

from companion.agent import Companion


class AgentLoopTests(unittest.TestCase):
    def test_runs_tool_then_answers(self):
        tool_turn = NS(stop_reason="tool_use", content=[
            NS(type="tool_use", id="t1", name="get_recipe", input={"item_name": "Bronze Ingot"})])
        final_turn = NS(stop_reason="end_turn", content=[NS(type="text", text="2x Copper Ore ...")])
        client = mock.MagicMock()
        client.beta.messages.create.side_effect = [tool_turn, final_turn]

        bot = Companion(client=client)
        self.assertEqual(bot.ask("bronze ingot?"), "2x Copper Ore ...")
        self.assertEqual(bot.tool_log, [{"name": "get_recipe", "input": {"item_name": "Bronze Ingot"}}])
        result = bot.messages[2]["content"][0]
        self.assertEqual(result["tool_use_id"], "t1")
        self.assertIn("Copper Ore", result["content"])
        self.assertFalse(result["is_error"])


if __name__ == "__main__":
    unittest.main()
