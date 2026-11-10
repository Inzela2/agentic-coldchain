# Cold-Chain Guardian
### An Autonomous AI Agent That Protects Vaccines in Transit, Built on the Model Context Protocol (MCP)

---

## 1. Problem Statement

Vaccines are among the most cost-effective tools in public health, but they are fragile. Most must be kept between **2 °C and 8 °C** from the factory to the clinic, the chain of refrigerated storage and transport known as the **cold chain**. If a vaccine gets too warm for too long, it gradually loses potency. If a freeze-sensitive vaccine such as Hepatitis B or Pentavalent freezes even briefly, it is permanently damaged, often with no visible sign.

When the cold chain breaks, the consequences are serious:

- **Children receive doses that don't protect them.** A damaged vaccine looks the same as a good one. A child can be "vaccinated" and still be unprotected, and nobody finds out until there is an outbreak.
- **Scarce doses are wasted.** The World Health Organization has estimated that a large share of vaccines are wasted worldwide, and temperature problems are a major cause. Every wasted batch means lost money and missed vaccination sessions in places that can least afford either.
- **Problems are found too late.** Trucks and coolers increasingly carry temperature sensors, but a sensor alarm alone fixes nothing. Someone must notice the alert, work out whether it's real, decide what to do, and do it before the damage is permanent. In practice, alarms are often noticed late, are frequent false alarms that people learn to ignore, or reach someone who has no authority to reroute a truck.

**Why this is a hard problem.** Handling a temperature alert correctly is not a single decision. It is a time-critical chain of judgments across several systems:

1. **Is the alert real?** Sensors fail. Diverting or destroying good vaccine because of a faulty sensor is a costly mistake too.
2. **What kind of damage is it?** Heat damage builds up slowly and may still be saved. Freeze damage is instant and permanent, so the batch must never be used.
3. **Can it still be saved?** That depends on the vaccine's tolerance, how much of it has already been used, and how far the truck still has to travel.
4. **Where can it go?** The nearest cold store may be full. The next one may be too far. Options must be checked against the clock.
5. **Did the action work?** A reroute or reservation must be confirmed, not assumed.
6. **Who must know?** The clinic must not use damaged doses and needs replacements. The truck must be repaired. Destroying stock needs human sign-off. Regulators need a record.

**Why a chatbot can't solve this.** A chatbot answers a question when someone asks one. This problem has to be handled the moment an alarm fires, by **acting on live systems** such as storage booking, fleet routing, stock and messaging. Each step depends on what the previous one revealed. Actions must be **verified**, and the plan must change when a step fails, for example when a store turns out to be full. That calls for an **AI agent**: a system that perceives, plans, acts through tools, observes the results, adapts, and learns.

**Problem statement in one sentence:**
> Temperature breaks in the vaccine cold chain silently destroy doses and leave children unprotected, because sensor alarms still depend on people to judge whether they are real, work out whether the batch can be saved, and coordinate a response across several systems before the damage becomes permanent. This project builds an autonomous agent that does this investigate–decide–act–verify loop itself through a standard tool protocol (MCP), keeps humans in charge of irreversible decisions, and learns from every alert.

---

## 2. Objectives

1. Build an agent that **responds to temperature alerts as they happen**, triggered by the monitoring system rather than by a human prompt.
2. **Tell real alerts from false ones** by cross-checking independent sensors before taking any action.
3. **Apply vaccine-specific rules correctly**: heat damage builds up over time, while freeze damage is instant and permanent.
4. **Save batches that can still be saved** by diverting them to a reachable cold store in time, and re-plan when an option fails.
5. **Never let damaged doses reach a child**: quarantine them with human approval and arrange replacements.
6. Expose all cold-chain systems as **tools on an MCP server**, so the agent can be connected to real systems later without changes.
7. Demonstrate the core agent fundamentals clearly, in a system that runs fully offline with no external APIs.

---

## 3. Proposed Solution

The system has two independent programs that communicate over MCP.

**The Cold-Chain MCP Server** simulates a vaccine distribution network and provides 11 tools:

| Category | Tools |
|---|---|
| Perception | `list_alerts` |
| Investigation (read-only) | `get_shipment`, `get_temperature_log`, `check_backup_logger`, `find_cold_storage` |
| Intervention (changes the network) | `reserve_cold_storage`, `reroute_shipment`, `request_replacement`, `quarantine_batch` (needs human approval) |
| Communication & audit | `notify`, `create_incident_report` |

**The Cold-Chain Guardian agent** connects to the server, discovers these tools at runtime, and handles each alert through the following loop:

```
ALERT ─> PLAN ─> ┌─> THINK    decide the next step from the evidence
                 │   GUARD    irreversible action? require human approval
                 │   ACT      call a tool through MCP
                 │   OBSERVE  add the result to short-term memory
                 │   REFLECT  verify, revise the plan if something failed
                 └── repeat until the alert is resolved or escalated (with a step limit)
           ─> REPORT ─> LEARN (save useful facts to long-term memory)
```

It follows a cold-chain officer's playbook:

1. Investigate before acting.
2. Never trust a single sensor.
3. Treat freezing as irreversible.
4. Compare elapsed and remaining time against the vaccine's heat budget.
5. Divert to the nearest cold store reachable in time.
6. Verify every action.
7. Tell everyone affected and document the incident.

---

## 4. System Architecture

```
 ┌──────────────────── Cold-Chain Guardian (agent) ────────────────────┐
 │  brain.py       plan / diagnose / decide / reflect / learn           │
 │  agent.py       the agent loop + human-approval guardrail            │
 │  memory.py      short-term (evidence) + long-term (learned facts)    │
 │  mcp_client.py  MCP client (JSON-RPC 2.0 over stdio)                 │
 │  display.py     live, color-coded trace of every decision            │
 └──────────────────────────────────┬───────────────────────────────────┘
                                    │  MCP: initialize · tools/list · tools/call
 ┌──────────────────────────────────▼───────────────────────────────────┐
 │  Cold-Chain MCP Server (server.py): simulated distribution network   │
 │  shipments · sensors · data loggers · cold stores · stock · messages │
 └──────────────────────────────────────────────────────────────────────┘
```

The agent and the tools are connected only through MCP. The simulated server could therefore be replaced by servers wrapping real systems, such as IoT sensor platforms, fleet management, warehouse booking and national stock systems, without changing the agent.

---

## 5. Demonstration Scenarios

The simulated network has four shipments in transit. Three raise alarms that look alike (a temperature outside 2–8 °C), but each needs a completely different response.

| Shipment | What's really happening | What the agent must work out | Outcome |
|---|---|---|---|
| **SHP-101** Measles-Rubella, 2,000 doses | Truck cooling failing, temperature rising | 18 of 60 min heat budget used. Arriving in 95 min would ruin the batch, so it must be cold within 42 min. The nearest store is **full**, so it re-plans to the next store reachable in time, reroutes, **verifies**, informs the clinic and requests a truck repair | **2,000 doses saved** |
| **SHP-102** Hepatitis B, 1,500 doses | Frozen for 38 min | Freeze-sensitive, and freezing is irreversible. Rerouting can't help. **Quarantine (human approval)**, verify, send replacement doses, warn the clinic not to use the batch | **Damaged doses stopped; replacements sent** |
| **SHP-103** Pentavalent, 1,200 doses | Faulty sensor | The sensor reads 31.5 °C after a physically impossible jump, while the independent logger reads 5.2 °C. **Don't touch the cargo**; get the sensor fixed | **False alarm: good vaccine not wasted** |
| **SHP-104** BCG | Healthy | No alert | **Left alone** |

**Learning:** on a second run the agent remembers which cold store accepted a diversion on the Riverside route and tries it first, saving a step when every minute counts. It also remembers that truck T-03's sensor has given false alarms before.

**Human in the loop:** with `-i`, a human approves or declines the quarantine. If it is declined, the agent does not deliver the batch. It escalates to the cold-chain officer and instructs that the batch must not be used until the officer decides.

---

## 6. Agent Fundamentals Demonstrated

| Fundamental | How it appears in the project |
|---|---|
| Perception | Triggered by temperature alerts, not by a user prompt |
| Tool discovery | Learns its capabilities at runtime through MCP `tools/list` |
| Planning | Builds an investigation plan before any intervention |
| Reasoning | Combines sensor trends, the backup logger, vaccine rules and travel time into a diagnosis |
| Tool use | Calls 11 tools through MCP `tools/call` |
| Verification | Re-checks the shipment after every reroute or quarantine |
| Reflection & re-planning | Switches to the next viable cold store when one is full; escalates when a human declines |
| Short-term memory | Evidence gathered for the current alert |
| Long-term memory | Proven cold stores per route and known faulty sensors, kept between runs |
| Guardrails | Human approval to destroy stock; never acts on a single sensor; step limit |
| Proportionality | Does nothing to the cargo on a false alarm |
| Accountability | Writes an incident report for every alert |

---

## 7. Technology Stack

- **Language:** Python 3.8+ (standard library only, no third-party packages)
- **Protocol:** Model Context Protocol (MCP), JSON-RPC 2.0 over stdio
- **Decision engine:** rule-based reasoning with the same interface an LLM-based agent would have (`plan`, `decide`, `reflect`, `lessons`)
- **Persistence:** JSON files for long-term memory and incident records

---

## 8. Scope and Limitations

- The network is **simulated**, and the scenarios are fixed so the demo can be reproduced.
- Vaccine stability is simplified to a single heat budget (minutes above 8 °C) and a freeze-sensitivity flag. Real stability data varies by product, and practice includes vial monitor checks and the "shake test" for suspected freezing.
- The decision engine is **rule-based**, which makes it transparent but limited to the situations it encodes. A real deployment would use an LLM for open-ended reasoning, with the same loop, tools and guardrails.
- Alerts are handled one at a time.

---

## 9. Future Enhancements

1. Replace the rule-based brain with an LLM implementing the same interface.
2. Connect to real IoT temperature platforms, fleet tracking and national stock systems through MCP servers.
3. Use **predictive alerts**: act when a temperature trend shows a breach is coming, before the safe range is crossed.
4. Handle several alerts at once while competing for the same scarce cold-store slots.
5. Add a dashboard for health officials showing doses saved, waste avoided and repeat-offender trucks.
6. Support more of the supply chain: ultra-cold vaccines (−70 °C), insulin, blood products and other heat-sensitive medicines.

---

## 10. Expected Outcomes

- **Fewer wasted doses**: batches that can still be saved are diverted within their remaining tolerance.
- **Fewer ineffective vaccinations**: damaged batches are quarantined and replaced, never quietly delivered.
- **Fewer false-alarm losses**: good vaccine is not destroyed or diverted because of a faulty sensor.
- **Faster response**: action within minutes of an alarm instead of hours.
- **A full audit trail** for every excursion, plus growing knowledge of reliable routes and faulty equipment.
- A clear, runnable reference for how AI agents and MCP fit together to solve a real public-health problem.
