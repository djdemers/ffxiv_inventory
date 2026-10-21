"""Run the test questions.

    python evals/run_evals.py            # offline: check the tools return the right facts
    python evals/run_evals.py --live     # also ask Claude each question (needs ANTHROPIC_API_KEY)

Offline checks call one tool with fixed arguments and look for expected
strings in its JSON output. Live checks ask the full assistant and look for
expected strings in its answer; questions with only "notes" need a human read.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from companion.tools import call_tool  # noqa: E402

QUESTIONS = Path(__file__).with_name("questions.jsonl")


def load() -> list[dict]:
    return [json.loads(line) for line in QUESTIONS.read_text().splitlines() if line.strip()]


def offline(questions: list[dict]) -> int:
    failures = 0
    for q in questions:
        check = q.get("check")
        if not check:
            continue
        output = json.dumps(call_tool(check["tool"], check["args"]), ensure_ascii=False)
        missing = [s for s in check["contains"] if s not in output]
        status = "FAIL" if missing else "ok  "
        failures += bool(missing)
        print(f"{status} {q['id']}" + (f"  missing {missing}" if missing else ""))
    return failures


def live(questions: list[dict]) -> int:
    from companion.agent import Companion

    failures = 0
    for q in questions:
        bot = Companion()
        answer = bot.ask(q["question"])
        missing = [s for s in q["must_include"] if s.lower() not in answer.lower()]
        tools_used = [c["name"] for c in bot.tool_log]
        status = "FAIL" if missing else ("look" if q.get("notes") else "ok  ")
        failures += bool(missing)
        print(f"\n{status} {q['id']}: {q['question']}\n  tools: {tools_used}")
        if missing:
            print(f"  missing {missing}")
        if q.get("notes"):
            print(f"  review: {q['notes']}")
        print("  " + answer.replace("\n", "\n  "))
    return failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="also run the questions through Claude")
    parser.add_argument("--only", help="run one question id")
    args = parser.parse_args()
    questions = [q for q in load() if not args.only or q["id"] == args.only]

    failures = offline(questions)
    print(f"\noffline: {failures} failed of {sum(1 for q in questions if q.get('check'))}")
    if args.live:
        live_failures = live(questions)
        print(f"\nlive: {live_failures} failed of {len(questions)}")
        failures += live_failures
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
