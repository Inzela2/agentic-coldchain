#!/usr/bin/env python3
"""
COLD-CHAIN MCP SERVER: a simulated vaccine distribution network exposed as MCP tools.

It stands in for the real systems a cold-chain officer uses: truck temperature
sensors, independent data loggers, shipment tracking, cold-storage booking,
fleet dispatch, stock management and messaging. Everything is simulated in
memory so the demo runs offline, but the protocol is real MCP.

Most vaccines must stay between 2 and 8 °C. Too warm for too long and they lose
potency. Freeze-sensitive vaccines are ruined by freezing even briefly, and the
damage cannot be undone. Either way, a child may receive a dose that doesn't work.

The network starts in the same state every time the server starts:
  SHP-101  Measles-Rubella  truck cooling failing     -> divert to cold storage in time
  SHP-102  Hepatitis B      frozen for 38 minutes     -> damage irreversible: quarantine + replace
  SHP-103  Pentavalent      primary sensor faulty     -> false alarm: cargo is fine
  SHP-104  BCG              healthy                   -> leave alone

MCP basics (stdio transport, JSON-RPC 2.0, one message per line):
  initialize, notifications/initialized, tools/list, tools/call, ping
Logs go to stderr only, because stdout carries protocol messages.
"""
import json
import os
import sys
from datetime import datetime

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "coldchain-tools-server", "version": "1.0.0"}
INCIDENTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "incidents.json")
SAFE_MIN, SAFE_MAX = 2.0, 8.0


def log(message):
    print(f"[server] {message}", file=sys.stderr, flush=True)


class ToolError(Exception):
    """The tool ran but could not do its job. Returned to the agent with isError=true."""


class RPCError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


# =============================================================================
# SIMULATED COLD-CHAIN NETWORK
# =============================================================================
SHIPMENTS = {
    "SHP-101": {
        "vaccine": "Measles-Rubella (MR)", "doses": 2000, "clinic": "Riverside Clinic", "truck": "T-12",
        "freeze_sensitive": False, "heat_budget_min": 60,
        "readings": [6.1, 7.4, 8.6, 9.3, 9.8], "backup_reading": 9.7,
        "minutes_above_8": 18, "minutes_below_0": 0,
        "eta_min": 95, "nearby_storage": {"Northgate Depot": 12, "Eastfield Hub": 25, "Central Vaccine Store": 70},
    },
    "SHP-102": {
        "vaccine": "Hepatitis B", "doses": 1500, "clinic": "Hillside Health Post", "truck": "T-07",
        "freeze_sensitive": True, "heat_budget_min": 60,
        "readings": [3.2, 1.1, -0.8, -1.5, -1.2], "backup_reading": -1.3,
        "minutes_above_8": 0, "minutes_below_0": 38,
        "eta_min": 40, "nearby_storage": {"Southbank Depot": 20, "Central Vaccine Store": 35},
    },
    "SHP-103": {
        "vaccine": "Pentavalent (DTP-HepB-Hib)", "doses": 1200, "clinic": "Lakeside Clinic", "truck": "T-03",
        "freeze_sensitive": True, "heat_budget_min": 60,
        "readings": [5.0, 5.1, 31.4, 31.6, 31.5], "backup_reading": 5.2,
        "minutes_above_8": 20, "minutes_below_0": 0,
        "eta_min": 30, "nearby_storage": {"Lakeside Depot": 15},
    },
    "SHP-104": {
        "vaccine": "BCG", "doses": 800, "clinic": "Valley Clinic", "truck": "T-09",
        "freeze_sensitive": False, "heat_budget_min": 60,
        "readings": [4.2, 4.4, 4.3, 4.5, 4.4], "backup_reading": 4.4,
        "minutes_above_8": 0, "minutes_below_0": 0,
        "eta_min": 50, "nearby_storage": {"Central Vaccine Store": 30},
    },
}
for _s in SHIPMENTS.values():
    _s.update(status="IN_TRANSIT", destination=_s["clinic"], handled=False)

STORAGE_FREE_SLOTS = {
    "Northgate Depot": 0, "Eastfield Hub": 6, "Central Vaccine Store": 40,
    "Southbank Depot": 3, "Lakeside Depot": 2,
}
RESERVATIONS = {}     # shipment_id -> store
CENTRAL_STOCK = {"Hepatitis B": 5000, "Measles-Rubella (MR)": 8000,
                 "Pentavalent (DTP-HepB-Hib)": 4000, "BCG": 3000}
MESSAGES = []


def _shipment(args):
    sid = str(args.get("shipment_id", "")).strip().upper()
    if sid not in SHIPMENTS:
        raise ToolError(f"Unknown shipment '{sid}'. Known: {', '.join(SHIPMENTS)}")
    return sid, SHIPMENTS[sid]


def _projected_exposure(s):
    """Minutes above 8 °C by arrival, if the cargo stays as warm as it is now."""
    warm_now = s["readings"][-1] > SAFE_MAX and s["status"] in ("IN_TRANSIT", "DIVERTED")
    return s["minutes_above_8"] + (s["eta_min"] if warm_now else 0)


# =============================================================================
# READ-ONLY TOOLS (observe the network)
# =============================================================================
def tool_list_alerts(args):
    lines = []
    for sid, s in SHIPMENTS.items():
        if s["handled"]:
            continue
        t = s["readings"][-1]
        if t > SAFE_MAX:
            lines.append(f"CRITICAL | {sid} | {t}°C, above safe range {SAFE_MIN:g}-{SAFE_MAX:g}°C")
        elif t < SAFE_MIN:
            lines.append(f"CRITICAL | {sid} | {t}°C, below safe range {SAFE_MIN:g}-{SAFE_MAX:g}°C (freezing risk)")
    return "\n".join(lines) if lines else "No active alerts."


def tool_get_shipment(args):
    sid, s = _shipment(args)
    return (f"{sid} | {s['vaccine']} x{s['doses']} | to {s['clinic']} | truck {s['truck']}\n"
            f"status={s['status']} destination={s['destination']} eta={s['eta_min']}min\n"
            f"rules: safe range {SAFE_MIN:g}-{SAFE_MAX:g}°C, heat budget {s['heat_budget_min']} min, "
            f"freeze_sensitive={'yes' if s['freeze_sensitive'] else 'no'}\n"
            f"exposure_so_far={s['minutes_above_8']}min "
            f"projected_exposure={_projected_exposure(s)}/{s['heat_budget_min']}min")


def tool_get_temperature_log(args):
    sid, s = _shipment(args)
    r = s["readings"]
    return (f"primary sensor, last {len(r)} readings (10 min apart): {', '.join(f'{x}' for x in r)} °C\n"
            f"current={r[-1]}°C min={min(r)}°C minutes_above_8={s['minutes_above_8']} "
            f"minutes_below_0={s['minutes_below_0']}")


def tool_check_backup_logger(args):
    sid, s = _shipment(args)
    return f"independent data logger in {sid}: current={s['backup_reading']}°C"


def tool_find_cold_storage(args):
    sid, s = _shipment(args)
    stores = sorted(s["nearby_storage"].items(), key=lambda kv: kv[1])
    return ("\n".join(f"{name}: {minutes} min away" for name, minutes in stores)
            + "\n(capacity is only confirmed when reserving)")


# =============================================================================
# ACTION TOOLS (change the network)
# =============================================================================
def tool_reserve_cold_storage(args):
    sid, s = _shipment(args)
    store = str(args.get("store", "")).strip()
    if store not in STORAGE_FREE_SLOTS:
        raise ToolError(f"Unknown store '{store}'")
    if STORAGE_FREE_SLOTS[store] <= 0:
        raise ToolError(f"{store} is FULL (0 free slots)")
    STORAGE_FREE_SLOTS[store] -= 1
    RESERVATIONS[sid] = store
    return f"Reserved a slot at {store} for {sid} ({s['doses']} doses). {STORAGE_FREE_SLOTS[store]} slot(s) left."


def tool_reroute_shipment(args):
    sid, s = _shipment(args)
    dest = str(args.get("destination", "")).strip()
    if RESERVATIONS.get(sid) != dest:
        raise ToolError(f"No reservation for {sid} at '{dest}'. Reserve first.")
    s["destination"], s["eta_min"], s["status"] = dest, s["nearby_storage"][dest], "DIVERTED"
    return f"Truck {s['truck']} rerouted: {sid} now heading to {dest}, arriving in {s['eta_min']} min."


def tool_quarantine_batch(args):
    sid, s = _shipment(args)
    s["status"] = "QUARANTINED"
    s["destination"] = "Central Vaccine Store (for disposal review)"
    return (f"{sid} quarantined ({s['doses']} doses of {s['vaccine']}): marked DO NOT USE, "
            f"truck {s['truck']} returning to central store. Reason: {args.get('reason', '-')}")


def tool_request_replacement(args):
    vaccine = str(args.get("vaccine", "")).strip()
    clinic = str(args.get("clinic", "")).strip()
    doses = int(args.get("doses", 0))
    if CENTRAL_STOCK.get(vaccine, 0) < doses:
        raise ToolError(f"Central stock has only {CENTRAL_STOCK.get(vaccine, 0)} doses of {vaccine}")
    CENTRAL_STOCK[vaccine] -= doses
    return (f"Replacement dispatched: {doses} doses of {vaccine} to {clinic}, ETA 3h 10m. "
            f"Central stock left: {CENTRAL_STOCK[vaccine]}.")


def tool_notify(args):
    to = str(args.get("recipient", "")).strip()
    message = str(args.get("message", "")).strip()
    if not to or not message:
        raise ToolError("Both 'recipient' and 'message' are required")
    MESSAGES.append({"to": to, "message": message})
    return f"Message sent to {to}."


def tool_create_incident_report(args):
    sid, s = _shipment(args)
    report = {k: args.get(k) for k in ("shipment_id", "finding", "actions", "outcome")}
    report["created"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    incidents = []
    if os.path.exists(INCIDENTS_FILE):
        with open(INCIDENTS_FILE, encoding="utf-8") as f:
            incidents = json.load(f)
    report["id"] = f"INC-{1000 + len(incidents) + 1}"
    incidents.append(report)
    with open(INCIDENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(incidents, f, indent=2, ensure_ascii=False)
    s["handled"] = True  # the alert is acknowledged
    return f"{report['id']} recorded ({report['outcome']})"


# =============================================================================
# TOOL REGISTRY: what the agent sees through tools/list
# =============================================================================
def _schema(*names, ints=()):
    props = {n: {"type": "integer" if n in ints else "string"} for n in names}
    return {"type": "object", "properties": props, "required": list(names)}


TOOLS = {
    "list_alerts": ("List active temperature alerts across all shipments.", _schema(), tool_list_alerts),
    "get_shipment": ("Shipment details, destination, ETA, vaccine rules and heat exposure.",
                     _schema("shipment_id"), tool_get_shipment),
    "get_temperature_log": ("Recent readings from the truck's primary temperature sensor.",
                            _schema("shipment_id"), tool_get_temperature_log),
    "check_backup_logger": ("Reading from the independent data logger packed with the vaccines.",
                            _schema("shipment_id"), tool_check_backup_logger),
    "find_cold_storage": ("Cold stores near a shipment, with travel time.", _schema("shipment_id"),
                          tool_find_cold_storage),
    "reserve_cold_storage": ("ACTION: reserve a cold-storage slot for a shipment.",
                             _schema("store", "shipment_id"), tool_reserve_cold_storage),
    "reroute_shipment": ("ACTION: send a shipment to a different destination (needs a reservation).",
                         _schema("shipment_id", "destination"), tool_reroute_shipment),
    "quarantine_batch": ("RISKY ACTION: mark a batch DO NOT USE and pull it from distribution.",
                         _schema("shipment_id", "reason"), tool_quarantine_batch),
    "request_replacement": ("ACTION: dispatch replacement doses from central stock.",
                            _schema("clinic", "vaccine", "doses", ints=("doses",)), tool_request_replacement),
    "notify": ("Send a message to a clinic, fleet maintenance or the cold-chain officer.",
               _schema("recipient", "message"), tool_notify),
    "create_incident_report": ("Record an incident and acknowledge its alert.",
                               _schema("shipment_id", "finding", "actions", "outcome"),
                               tool_create_incident_report),
}


# =============================================================================
# PROTOCOL HANDLING
# =============================================================================
def handle_request(method, params):
    if method == "initialize":
        return {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}}, "serverInfo": SERVER_INFO}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [{"name": n, "description": d, "inputSchema": s} for n, (d, s, _) in TOOLS.items()]}
    if method == "tools/call":
        name = params.get("name")
        if name not in TOOLS:
            raise RPCError(-32602, f"Unknown tool: {name}")
        log(f"calling {name}({params.get('arguments')})")
        try:
            text = TOOLS[name][2](params.get("arguments") or {})
            return {"content": [{"type": "text", "text": text}], "isError": False}
        except ToolError as e:
            return {"content": [{"type": "text", "text": str(e)}], "isError": True}
    raise RPCError(-32601, f"Method not found: {method}")


def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def main():
    log("started")
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            continue
        if "id" not in msg:  # notification: never answered
            log(f"notification: {msg.get('method')}")
            continue
        try:
            send({"jsonrpc": "2.0", "id": msg["id"], "result": handle_request(msg.get("method"), msg.get("params") or {})})
        except RPCError as e:
            send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": e.code, "message": e.message}})
        except Exception as e:
            send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32603, "message": str(e)}})


if __name__ == "__main__":
    main()
