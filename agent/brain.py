"""
BRAIN: decides what to do next. Here it plays the role of a cold-chain officer.

In a production agent this is an LLM. Here it is readable rules, so the project
runs offline and every decision can be traced. The interface is the one an
LLM-based brain would have:

  plan(goal, tools, long_term) -> initial steps            (PLANNING)
  decide(short_term)           -> next Action, or Finish   (REASONING)
  reflect(short_term)          -> insight, may change plan (REFLECTION / RE-PLANNING)
  lessons()                    -> what to remember         (LEARNING)

The playbook it follows:
  1. Investigate before acting: shipment rules, sensor history, independent logger.
  2. Never act on one sensor alone. If the two disagree, suspect the sensor.
  3. Freezing a freeze-sensitive vaccine is irreversible. Pull the batch, never deliver it.
  4. Heat damage builds up. Compare the time already used and the time to arrival
     with the vaccine's heat budget.
  5. If it won't last until arrival, divert to the nearest cold store reachable in time.
  6. Verify every action, and re-plan when one fails (a store is full, a human declines).
  7. Tell the people affected, and always write an incident report.
"""
import re
from dataclasses import dataclass

RISKY_TOOLS = {"quarantine_batch"}  # destroys stock -> needs human approval
SAFE_MAX = 8.0


@dataclass
class Action:
    tool: str
    args: dict
    thought: str
    purpose: str = ""      # investigate | act | verify | notify | report
    hypothesis: str = ""


@dataclass
class Finish:
    answer: str
    thought: str


class RuleBasedBrain:
    # ------------------------------------------------------------------ PLAN
    def plan(self, goal, tools, long_term):
        self.sid = goal["id"]
        self.alert = goal["reason"]
        self.tools = {t["name"] for t in tools}
        self.long_term = long_term
        self.queue = []
        self.candidates = []       # cold stores still worth trying
        self.actions_log = []
        self.finding = "under investigation"
        self.outcome = "investigating"
        self.mode = None           # divert | quarantine | sensor | monitor
        self.info = {}
        self._lessons = []
        self.diagnosed = False
        self.reported = False

        runbook = [
            ("get_shipment", "Start with the facts: what vaccine, where it's going, and its rules."),
            ("get_temperature_log", "Look at the temperature trend, not just the latest reading."),
            ("check_backup_logger", "Cross-check with the independent logger. One sensor alone isn't proof."),
        ]
        for tool, why in runbook:
            if tool in self.tools:
                self.queue.append(Action(tool, {"shipment_id": self.sid}, why, "investigate"))
        return list(self.queue)

    # ---------------------------------------------------------------- DECIDE
    def decide(self, short_term):
        if self.queue:
            return self.queue.pop(0)
        if not self.diagnosed:
            self.diagnosed = True
            return self._diagnose(short_term)
        if not self.reported and "create_incident_report" in self.tools:
            self.reported = True
            return Action("create_incident_report", {
                "shipment_id": self.sid, "finding": self.finding,
                "actions": "; ".join(self.actions_log) or "none", "outcome": self.outcome},
                "Record what happened. Health authorities need an audit trail for every excursion.", "report")
        return Finish(self._summary(short_term), "Alert handled and documented. Done.")

    # ------------------------------------------------------------- DIAGNOSE
    def _diagnose(self, short_term):
        ship = short_term.find("get_shipment")
        tlog = short_term.find("get_temperature_log")
        backup = short_term.find("check_backup_logger")

        m = re.search(r"\| (.+?) x(\d+) \| to (.+?) \| truck (\S+)", ship)
        i = self.info
        i["vaccine"], i["doses"], i["clinic"], i["truck"] = m.group(1), int(m.group(2)), m.group(3), m.group(4)
        i["budget"] = _num(r"heat budget (\d+) min", ship)
        i["freeze_sensitive"] = "freeze_sensitive=yes" in ship
        i["eta"] = _num(r"eta=(\d+)min", ship)
        i["exposure"] = _num(r"exposure_so_far=(\d+)min", ship)
        readings = [float(x) for x in re.search(r": ([-\d., ]+) °C", tlog).group(1).split(",")]
        current = _num(r"current=(-?[\d.]+)°C", tlog, float)
        lowest = _num(r"min=(-?[\d.]+)°C", tlog, float)
        below0 = _num(r"minutes_below_0=(\d+)", tlog)
        backup_t = _num(r"current=(-?[\d.]+)°C", backup, float)
        biggest_jump = max(abs(b - a) for a, b in zip(readings, readings[1:]))

        # Rule 1: the two independent measurements disagree -> the sensor is suspect, not the vaccine.
        if backup_t is not None and abs(current - backup_t) > 5:
            self.mode, self.outcome = "sensor", "false alarm: cargo safe, delivery continues"
            self.finding = f"primary sensor fault on {i['truck']} (reads {current}°C, logger {backup_t}°C)"
            known = self.long_term.get("faulty_sensors", {}).get(i["truck"])
            hyp = (f"The primary sensor jumped {biggest_jump:.1f}°C in ten minutes, which an insulated "
                   f"cooler can't physically do, and the independent logger reads {backup_t}°C, inside the safe range. "
                   f"The vaccine is fine; the sensor isn't.")
            if known:
                hyp += f" Long-term memory: {i['truck']}'s sensor gave a false alarm before."
            self.actions_log.append("flagged sensor for repair")
            self._lessons.append(("faulty_sensors", i["truck"], "primary sensor false alarm"))
            return Action("notify", {"recipient": "fleet-maintenance", "message":
                          f"Truck {i['truck']}: primary temperature sensor faulty (reads {current}°C, logger "
                          f"{backup_t}°C). Replace it at next stop. Cargo {self.sid} unaffected."},
                          "No action on the cargo. Don't divert or destroy good vaccine because of a bad sensor. "
                          "Get the sensor fixed.", "notify", hyp)

        # Rule 2: a freeze-sensitive vaccine has been frozen -> irreversible.
        if i["freeze_sensitive"] and below0 and below0 > 0:
            self.mode = "quarantine"
            self.finding = f"{i['vaccine']} frozen for {below0} min (low {lowest}°C); freeze damage is irreversible"
            hyp = (f"{i['vaccine']} is freeze-sensitive and has been below 0°C for {below0} min "
                   f"(confirmed by the logger at {backup_t}°C). Frozen doses lose potency for good. "
                   f"Rerouting or rewarming can't undo it, and delivering would mean giving children "
                   f"a dose that may not protect them.")
            return Action("quarantine_batch", {"shipment_id": self.sid, "reason":
                          f"frozen {below0} min, low {lowest}°C"},
                          "Pull the batch from distribution first, then get the clinic replacement doses.",
                          "act", hyp)

        # Rule 3: too warm. Will it last until arrival?
        if current > SAFE_MAX:
            remaining = i["budget"] - i["exposure"]
            projected = i["exposure"] + i["eta"]
            trend = f"{readings[0]} -> {readings[-1]}°C"
            if projected <= i["budget"]:
                self.mode, self.outcome = "monitor", "delivered within stability budget"
                self.finding = f"minor heat excursion ({projected}/{i['budget']} min projected)"
                self.actions_log.append("clinic told to check vial monitors")
                hyp = (f"It's warm ({trend}), but {i['exposure']} min used + {i['eta']} min to arrival = "
                       f"{projected} min, within the {i['budget']} min heat budget. Diverting would only delay doses.")
                return Action("notify", {"recipient": i["clinic"], "message":
                              f"{self.sid} arriving in {i['eta']} min after a short warm spell. Check the vial "
                              f"monitors and refrigerate immediately."},
                              "Proportionate response: deliver, and warn the clinic.", "notify", hyp)

            self.mode = "divert"
            self.finding = f"truck {i['truck']} cooling failure ({trend})"
            hyp = (f"Temperature is climbing ({trend}) and the logger agrees ({backup_t}°C), so the truck's cooling "
                   f"is failing. {i['exposure']} of {i['budget']} min heat budget used. Arriving in {i['eta']} min "
                   f"would mean {projected} min: the batch would be ruined before it reaches {i['clinic']}. "
                   f"It must be cold within {remaining} min.")
            return Action("find_cold_storage", {"shipment_id": self.sid},
                          f"Find a cold store reachable within {remaining} min.", "investigate", hyp)

        self.mode, self.outcome, self.finding = "monitor", "no action needed", "readings back in range"
        return Action("notify", {"recipient": "cold-chain-officer", "message":
                      f"{self.sid}: alert cleared on its own; readings in range."},
                      "Nothing to fix. Tell the officer and close.", "notify")

    # --------------------------------------------------------------- REFLECT
    def reflect(self, short_term):
        last = short_term.last()
        if last is None:
            return None
        i = self.info

        # -- choosing a cold store ------------------------------------------
        if last.tool == "find_cold_storage" and not last.is_error:
            remaining = i["budget"] - i["exposure"]
            stores = [(n, int(t)) for n, t in re.findall(r"^(.+?): (\d+) min away", last.observation, re.M)]
            viable = [n for n, t in stores if t <= remaining]
            too_far = [f"{n} ({t} min)" for n, t in stores if t > remaining]
            self.candidates = list(viable)
            note = ""
            preferred = self.long_term.get("preferred_storage", {}).get(i["clinic"])
            if preferred in self.candidates:
                self.candidates.remove(preferred)
                self.candidates.insert(0, preferred)
                note = f" Long-term memory: {preferred} accepted a diversion on this route before, so I'll try it first."
            if not self.candidates:
                return self._escalate("No cold store can be reached in time.")
            self._queue_reservation()
            return (f"{remaining} min of budget left. Reachable in time: {', '.join(viable)}."
                    + (f" Too far: {', '.join(too_far)}." if too_far else "") + note)

        # -- reservation result ---------------------------------------------
        if last.tool == "reserve_cold_storage":
            store = last.args["store"]
            if last.is_error:
                self.actions_log.append(f"{store} full")
                if self.candidates:
                    self._queue_reservation()
                    nxt = self.queue[0].args["store"]
                    return f"{store} is full. Re-planning: trying {nxt}, which is still reachable in time."
                return self._escalate(f"{store} is full and no other store is reachable in time.")
            self.actions_log.append(f"reserved {store}")
            self.queue.insert(0, Action("reroute_shipment", {"shipment_id": self.sid, "destination": store},
                                        f"Slot confirmed. Now send the truck to {store}.", "act"))
            return None

        # -- actions that must be verified ----------------------------------
        if last.tool == "reroute_shipment" and not last.is_error:
            self.actions_log.append(f"rerouted to {last.args['destination']}")
            self.queue.insert(0, Action("get_shipment", {"shipment_id": self.sid},
                                        "Verify: is the truck really heading there, and will the vaccine survive the trip?",
                                        "verify"))
            return "Reroute sent, but I won't assume it worked. Adding a verification step."

        if last.tool == "quarantine_batch":
            if last.is_error:
                self.actions_log.append("quarantine declined by human")
                return self._escalate("The quarantine was declined, so a human has to decide.")
            self.actions_log.append("batch quarantined")
            self.queue.insert(0, Action("get_shipment", {"shipment_id": self.sid},
                                        "Verify the batch is really out of distribution before replacing it.", "verify"))
            return "Quarantine requested. Verifying before the next step."

        if last.purpose == "verify":
            return self._check_verification(last.observation)

        if last.tool == "request_replacement" and not last.is_error:
            self.actions_log.append("replacement dispatched")
        if last.tool == "notify" and not last.is_error and last.args["recipient"] == i.get("clinic"):
            self.actions_log.append(f"informed {i['clinic']}")
        if last.is_error:
            return "That step failed. I'll carry on and record it in the report."
        return None

    def _check_verification(self, obs):
        i = self.info
        if self.mode == "divert":
            p = re.search(r"projected_exposure=(\d+)/(\d+)min", obs)
            projected, budget = int(p.group(1)), int(p.group(2))
            if "status=DIVERTED" in obs and projected <= budget:
                store = re.search(r"destination=(.+?) eta=", obs).group(1)
                self.outcome = f"{i['doses']} doses saved ({projected}/{budget} min heat exposure)"
                self._lessons.append(("preferred_storage", i["clinic"], store))
                self.queue[0:0] = [
                    Action("notify", {"recipient": i["clinic"], "message":
                           f"Your {i['vaccine']} delivery ({self.sid}) was diverted to {store} because the truck's "
                           f"cooling failed. The doses are safe; onward delivery will be rescheduled."},
                           "The clinic is expecting these doses. Tell them, so they can reschedule vaccination sessions.",
                           "notify"),
                    Action("notify", {"recipient": "fleet-maintenance", "message":
                           f"Truck {i['truck']}: refrigeration unit failing. Take it out of service for repair."},
                           "Fix the root cause, or the next shipment on this truck will have the same problem.", "notify"),
                ]
                return f"Verified: heading to {store}, total exposure will be {projected}/{budget} min. The batch is safe."
            return self._escalate("Verification failed: the batch still won't make it in time.")

        if self.mode == "quarantine":
            if "status=QUARANTINED" in obs:
                self.outcome = "batch quarantined; replacement dispatched"
                self.queue[0:0] = [
                    Action("request_replacement", {"clinic": i["clinic"], "vaccine": i["vaccine"], "doses": i["doses"]},
                           "Children at the clinic still need these vaccines. Send good doses.", "act"),
                    Action("notify", {"recipient": i["clinic"], "message":
                           f"Shipment {self.sid} ({i['vaccine']}) was frozen in transit and has been withdrawn. "
                           f"Replacement doses are on the way. Please do not use any doses from {self.sid}."},
                           "Make sure the clinic never uses the damaged doses, and knows replacements are coming.",
                           "notify"),
                ]
                return "Verified: the batch is quarantined. Now replace it."
            return self._escalate("The batch is not showing as quarantined.")
        return None

    def _queue_reservation(self):
        store = self.candidates.pop(0)
        self.queue.insert(0, Action("reserve_cold_storage", {"store": store, "shipment_id": self.sid},
                                    f"Try the nearest viable store: {store}.", "act"))

    def _escalate(self, why):
        self.outcome = "escalated to cold-chain officer"
        self.queue.insert(0, Action("notify", {"recipient": "cold-chain-officer", "message":
                                    f"{self.sid} ({self.info.get('vaccine')}): {self.finding}. {why} "
                                    f"Actions so far: {'; '.join(self.actions_log) or 'none'}. Batch must not be "
                                    f"administered until you decide."},
                                    "I can't resolve this safely on my own. Hand over with everything I found.",
                                    "notify"))
        self.actions_log.append("escalated to cold-chain officer")
        return f"{why} Escalating to a human."

    # ---------------------------------------------------------------- LEARN
    def lessons(self):
        """(memory bucket, key, value) facts worth keeping for future alerts."""
        return list(self._lessons) if "escalated" not in self.outcome else []

    def _summary(self, short_term):
        report = short_term.find("create_incident_report")
        inc = report.split(" ")[0] if report else "-"
        i = self.info
        return (f"Shipment:  {self.sid} ({i.get('vaccine')} x{i.get('doses')} for {i.get('clinic')})\n"
                f"Alert:     {self.alert}\n"
                f"Finding:   {self.finding}\n"
                f"Actions:   {', '.join(self.actions_log) or 'none'}\n"
                f"Outcome:   {self.outcome}  ({inc}, {len(short_term.steps)} steps)")


def _num(pattern, text, cast=int):
    m = re.search(pattern, text or "")
    return cast(m.group(1)) if m else None
