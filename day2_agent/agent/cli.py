"""CLI: copilot-triage "ticket text"   (or: copilot-triage --file ticket.txt)

Prints the tool-call trace as it happens, then the structured result."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from day2_agent.agent.loop import run_triage


def _print_event(event: dict) -> None:
    kind = event.get("type")
    if kind == "iteration":
        print(f"--- iteration {event['n']} ---", file=sys.stderr)
    elif kind == "tool_call":
        print(f"  -> {event['name']}({json.dumps(event['args'])})", file=sys.stderr)
    elif kind == "tool_result":
        print(f"  <- {event['name']} [{event['chars']} chars]", file=sys.stderr)
    elif kind in ("repair", "nudge"):
        print(f"  !! {kind}: {event.get('reason') or event.get('error')}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="Triage a support ticket with the agent.")
    parser.add_argument("ticket", nargs="?", help="Ticket text (or use --file).")
    parser.add_argument("--file", type=Path, help="Read the ticket from a file.")
    args = parser.parse_args()

    text = args.file.read_text() if args.file else args.ticket
    if not text:
        parser.error("provide ticket text or --file")

    result = asyncio.run(run_triage(text, on_event=_print_event))
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
