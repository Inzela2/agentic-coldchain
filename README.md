# Cold-Chain Guardian: Keeping Vaccines Safe in Transit

An AI agent that responds to vaccine temperature alarms by itself. It checks
whether the alarm is **real**, works out whether the batch can still be
**saved**, **acts** (reserves cold storage, reroutes the truck, quarantines
damaged doses, orders replacements), **verifies** every action, **re-plans**
when something fails, and **learns** for next time. All of this goes through
tools on an **MCP server**.

- No API keys, no LLM calls, no internet.
- No dependencies: Python 3.8+ standard library only.
- Every decision is printed so you can follow the agent's reasoning.

For the full problem statement, objectives and design, see
**[PROJECT_DESCRIPTION.md](PROJECT_DESCRIPTION.md)**.

## Run it

```bash
python run_demo.py --reset     # first run: handles 3 alerts from scratch
python run_demo.py             # second run: uses what it learned (long-term memory)
python run_demo.py -i          # human-in-the-loop: YOU approve or decline the quarantine
python run_demo.py --protocol  # show the raw MCP JSON-RPC messages
python run_demo.py --fast      # no pauses
```

## Three alarms that look alike, three different right answers

| Shipment | What's really happening | Agent's path | Result |
|---|---|---|---|
| SHP-101 Measles-Rubella | truck cooling failing | investigate → find store in time → **nearest is full, re-plan** → reserve → reroute → **verify** → tell clinic + maintenance | 2,000 doses saved |
| SHP-102 Hepatitis B | frozen 38 min (irreversible) | investigate → **quarantine (human approval)** → verify → replacement → warn clinic | damaged doses never used |
| SHP-103 Pentavalent | faulty sensor | investigate → **backup logger disagrees** → leave cargo alone → fix sensor | good vaccine not wasted |
| SHP-104 BCG | healthy | no alert | left alone |

## Architecture

```
 ┌───────────────────────── AGENT (agent/) ─────────────────────────┐
 │   brain.py ──decides──> agent.py <──remembers── memory.py        │
 │                            │ (loop + approval guard)             │
 │                      mcp_client.py                               │
 └────────────────────────────┼──────────────────────────────────────┘
                              │ JSON-RPC 2.0 over stdin/stdout (MCP)
 ┌────────────────────────────▼──────────────────────────────────────┐
 │ MCP SERVER (mcp_server/server.py): simulated cold-chain network   │
 │ list_alerts · get_shipment · get_temperature_log ·                │
 │ check_backup_logger · find_cold_storage · reserve_cold_storage ·  │
 │ reroute_shipment · quarantine_batch · request_replacement ·       │
 │ notify · create_incident_report                                   │
 └───────────────────────────────────────────────────────────────────┘
```

## Agent fundamentals: where to find them

| Concept | Where |
|---|---|
| Perception (triggered by alerts) | `agent.py` → `check_alerts()` |
| Tool discovery (`tools/list`) | `agent.py` → `discover_tools()` |
| Planning (investigate before acting) | `brain.py` → `plan()` |
| Reasoning / diagnosis | `brain.py` → `_diagnose()` |
| Tool use (`tools/call`) | `mcp_client.py` → `call_tool()` |
| Verification + reflection + re-planning | `brain.py` → `reflect()`, `_check_verification()` |
| Short-term memory (evidence) | `memory.py` → `ShortTermMemory` |
| Long-term memory (learned facts) | `memory.py` → `LongTermMemory`, `agent.py` → `_learn()` |
| Guardrails (approval, step limit) | `agent.py` → `_approved()`, `max_steps` |
| MCP protocol | `mcp_server/server.py` |

## Reading the output

`THINK` reasoning · `DIAGNOSE` conclusion from the evidence · `GUARD` approval
check · `ACT` tool call · `OBSERVE` result · `ERROR` failed tool · `REFLECT`
verification and re-planning · `MEMORY` something learned.

## Why rule-based, and how to plug in an LLM

The brain uses readable rules so the project runs offline and every decision
can be traced. It has the same interface an LLM brain would:

```python
brain.plan(goal, tools, long_term)  # -> initial steps
brain.decide(short_term)            # -> Action | Finish
brain.reflect(short_term)           # -> insight; may change the plan
brain.lessons()                     # -> facts to remember
```

To upgrade, implement these with a model that receives the alert, the tool
list and the evidence gathered so far. Nothing else changes.

## Use the server with Claude Desktop

`server.py` speaks real MCP. Add to `claude_desktop_config.json`:

```json
{ "mcpServers": { "coldchain": {
    "command": "python",
    "args": ["/full/path/to/coldchain-agent/mcp_server/server.py"] } } }
```

## Exercises

1. Add a shipment with a small excursion that is **within** budget. The agent should deliver it and warn the clinic. That path already exists in `brain.py`.
2. Make every cold store near SHP-101 full and watch the agent escalate.
3. Add **predictive alerts**: act when the trend shows 8 °C will be crossed soon.
4. Make `reroute_shipment` also require approval, and decline it with `-i`.
