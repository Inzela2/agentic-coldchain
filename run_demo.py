#!/usr/bin/env python3
"""
Cold-Chain Guardian: an autonomous agent that protects vaccines in transit, working through MCP.

  python run_demo.py              # handle all active alerts (risky actions auto-approved)
  python run_demo.py -i           # YOU approve or decline quarantines (human-in-the-loop)
  python run_demo.py --protocol   # also show the raw MCP JSON-RPC messages
  python run_demo.py --fast       # no pauses
  python run_demo.py --reset      # forget what the agent learned and past incident reports

Run it twice: on the second run the agent uses what it learned the first time.
"""
import argparse
import sys
from pathlib import Path

from agent.agent import Agent
from agent.brain import RuleBasedBrain
from agent.display import Display
from agent.mcp_client import MCPClient
from agent.memory import LongTermMemory

ROOT = Path(__file__).resolve().parent
SERVER = ROOT / "mcp_server" / "server.py"
MEMORY_FILE = ROOT / "agent_memory.json"
INCIDENTS_FILE = ROOT / "mcp_server" / "incidents.json"


def ask_human(action):
    answer = input(f"\n  >>> Approve {action.tool} for {action.args['shipment_id']} "
                   f"({action.args.get('reason', '')})? [y/n] ").strip().lower()
    return answer in {"y", "yes"}


def main():
    parser = argparse.ArgumentParser(description="Vaccine cold-chain agent over MCP (no APIs)")
    parser.add_argument("-i", "--interactive", action="store_true", help="approve quarantines yourself")
    parser.add_argument("-p", "--protocol", action="store_true", help="show raw JSON-RPC messages")
    parser.add_argument("--fast", action="store_true", help="no pauses between steps")
    parser.add_argument("--reset", action="store_true", help="clear long-term memory and incident reports")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if args.reset:
        for f in (MEMORY_FILE, INCIDENTS_FILE):
            if f.exists():
                f.unlink()

    display = Display(delay=0 if args.fast else 0.35)
    display.banner("COLD-CHAIN GUARDIAN: keeping vaccines safe in transit",
                   "perceive -> investigate -> act -> verify -> re-plan -> learn")

    display.section("CONNECTING TO COLD-CHAIN MCP SERVER (initialize handshake)")
    client = MCPClient([sys.executable, str(SERVER)],
                       on_message=display.protocol if args.protocol else None)
    with client:
        info = client.server_info
        display.info(f"connected to {info.get('name')} v{info.get('version')}")

        long_term = LongTermMemory(MEMORY_FILE)
        if long_term.data:
            display.info(f"long-term memory from earlier runs: {long_term.data}")

        agent = Agent(client, RuleBasedBrain(), long_term, display,
                      approver=ask_human if args.interactive else None)
        agent.discover_tools()

        for alert in agent.check_alerts():
            agent.handle(alert)

        print()
        display.info("Re-checking monitoring after the agent's work:")
        agent.check_alerts()
        print()
        display.info("Run again to see long-term memory in action. Try -i to decide on quarantines yourself,")
        display.info("or --protocol --fast to watch the raw MCP messages.")


if __name__ == "__main__":
    main()
