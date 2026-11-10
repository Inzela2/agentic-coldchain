"""
DISPLAY: makes the agent's inner workings visible in the terminal.
Pure presentation, no agent logic lives here.
"""
import json
import os
import sys
import textwrap
import time

if os.name == "nt":
    os.system("")  # enables ANSI colors in Windows terminals

COLORS = {
    "bold": "1", "dim": "2", "red": "31", "green": "32", "yellow": "33",
    "blue": "34", "magenta": "35", "cyan": "36", "gray": "90",
}
WIDTH = 72


class Display:
    def __init__(self, color=None, delay=0.35):
        if color is None:
            color = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
        self.color = color
        self.delay = delay

    # ---- helpers -----------------------------------------------------------
    def _c(self, text, *styles):
        if not self.color:
            return text
        codes = ";".join(COLORS[s] for s in styles)
        return f"\033[{codes}m{text}\033[0m"

    def _pause(self):
        if self.delay:
            time.sleep(self.delay)

    def _label(self, label, color, text, indent=12):
        wrapped = textwrap.wrap(text, WIDTH - indent) or [""]
        first = self._c(f"  {label:<{indent - 3}}", "bold", color)
        print(f"{first} {wrapped[0]}")
        for line in wrapped[1:]:
            print(" " * indent + line)

    # ---- sections ----------------------------------------------------------
    def banner(self, title, subtitle=""):
        line = "═" * WIDTH
        print(self._c(line, "cyan"))
        print(self._c(f"  {title}", "bold", "cyan"))
        if subtitle:
            print(self._c(f"  {subtitle}", "gray"))
        print(self._c(line, "cyan"))

    def section(self, title):
        print()
        print(self._c(f"── {title} " + "─" * max(0, WIDTH - len(title) - 4), "blue"))

    def info(self, text):
        print(self._c(f"  {text}", "gray"))

    def tools(self, tools):
        self.section(f"DISCOVERED {len(tools)} TOOLS VIA MCP (tools/list)")
        for t in tools:
            params = ", ".join(t.get("inputSchema", {}).get("properties", {})) or "-"
            print(f"  {self._c(t['name'], 'bold', 'green'):<30} ({params})  "
                  + self._c(t.get("description", ""), "gray"))

    def alerts(self, alerts):
        self.section(f"ACTIVE ALERTS ({len(alerts)})")
        if not alerts:
            print("  " + self._c("All clear. Every alert has been handled.", "bold", "green"))
        for a in alerts:
            color = "red" if a["severity"] == "CRITICAL" else "yellow"
            print(f"  {self._c(a['severity'], 'bold', color):<10} {self._c(a['id'], 'bold')}  "
                  + self._c(a["reason"], "gray"))

    def incident(self, goal):
        print()
        print(self._c("═" * WIDTH, "yellow"))
        print(self._c("  ALERT: ", "bold", "yellow") + self._c(goal["id"], "bold")
              + self._c(f"  ({goal['reason']})", "gray"))
        print(self._c("═" * WIDTH, "yellow"))

    def plan(self, plan):
        self.section("PLAN (investigate before acting)")
        if not plan:
            self.info("(no diagnostic tools available)")
        for i, a in enumerate(plan, 1):
            print(f"  {i}. {self._c(a.tool, 'green')}({json.dumps(a.args, ensure_ascii=False)})")
        self.section("EXECUTION")
        self._pause()

    # ---- the loop ----------------------------------------------------------
    def thought(self, step, text):
        print(self._c(f"  step {step}", "gray"))
        self._label("THINK", "magenta", text)
        self._pause()

    def action(self, tool, args):
        self._label("ACT", "blue", f"{tool}({json.dumps(args, ensure_ascii=False)})")
        self._pause()

    def observation(self, text, is_error):
        if is_error:
            self._label("ERROR", "red", text)
        else:
            for i, line in enumerate(text.splitlines()):
                self._label("OBSERVE" if i == 0 else "", "green", line)
        self._pause()

    def hypothesis(self, text):
        self._label("DIAGNOSE", "cyan", text)
        self._pause()

    def approval(self, tool, ok):
        if ok is None:
            text = f"{tool} is a risky action. Auto-approved (demo mode; use -i to decide yourself)."
        else:
            text = f"{tool} {'approved' if ok else 'DECLINED'} by human operator"
        self._label("GUARD", "red", text)
        self._pause()

    def reflection(self, text):
        self._label("REFLECT", "yellow", text)
        self._pause()

    def memory(self, text):
        self._label("MEMORY", "cyan", text)

    def warning(self, text):
        self._label("STOP", "red", text)

    def final(self, answer):
        self.section("OUTCOME")
        for line in answer.splitlines():
            for wrapped in textwrap.wrap(line, WIDTH - 2, subsequent_indent=" " * 11) or [""]:
                print("  " + self._c(wrapped, "bold"))

    # ---- raw protocol view (--protocol) ------------------------------------
    def protocol(self, direction, message):
        who = "agent  -> server" if direction == "->" else "server -> agent "
        text = json.dumps(message, ensure_ascii=False)
        if len(text) > 160:
            text = text[:157] + "..."
        print(self._c(f"    [{who}] {text}", "dim"))
