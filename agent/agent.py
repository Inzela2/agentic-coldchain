"""
THE AGENT LOOP: the heart of every agent.

    alert ──> PLAN ──> ┌─> THINK   brain picks the next action
                       │   GUARD   risky action (quarantine)? ask a human first
                       │   ACT     call a tool through MCP
                       │   OBSERVE store the result in short-term memory
                       │   REFLECT verify, update the hypothesis, re-plan
                       └── repeat until FINISH or max_steps
                 ──> LEARN  save the lesson in long-term memory

The agent itself is small. It wires together:
  brain   -> decides     (agent/brain.py)
  client  -> acts        (agent/mcp_client.py, talks to the MCP server)
  memory  -> remembers   (agent/memory.py)
  display -> shows you   (agent/display.py)
"""
from .brain import RISKY_TOOLS, Finish
from .memory import ShortTermMemory, Step


class Agent:
    def __init__(self, client, brain, long_term, display, approver=None, max_steps=12):
        self.client = client
        self.brain = brain
        self.long_term = long_term
        self.display = display
        self.approver = approver      # function(action) -> bool; None = auto-approve
        self.max_steps = max_steps    # safety guard: an agent must always stop
        self.tools = []

    def discover_tools(self):
        """Ask the MCP server what the agent is able to do."""
        self.tools = self.client.list_tools()
        self.display.tools(self.tools)
        return self.tools

    def check_alerts(self):
        """PERCEPTION: the agent is triggered by the environment, not by a chat message."""
        text, _ = self.client.call_tool("list_alerts", {})
        alerts = []
        for line in text.splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) == 3:
                alerts.append({"severity": parts[0], "id": parts[1], "reason": parts[2]})
        self.display.alerts(alerts)
        return alerts

    def handle(self, goal):
        self.display.incident(goal)
        short_term = ShortTermMemory()  # fresh evidence board per alert

        plan = self.brain.plan(goal, self.tools, self.long_term)
        self.display.plan(plan)

        for step_no in range(1, self.max_steps + 1):
            decision = self.brain.decide(short_term)

            if isinstance(decision, Finish):
                self.display.thought(step_no, decision.thought)
                self.display.final(decision.answer)
                self._learn(goal)
                return decision.answer

            if decision.hypothesis:
                self.display.hypothesis(decision.hypothesis)
            self.display.thought(step_no, decision.thought)

            if decision.tool in RISKY_TOOLS and not self._approved(decision):
                observation, is_error = "Human operator declined this action.", True
            else:
                self.display.action(decision.tool, decision.args)
                observation, is_error = self.client.call_tool(decision.tool, decision.args)
            self.display.observation(observation, is_error)

            short_term.add(Step(decision.thought, decision.tool, decision.args,
                                observation, is_error, decision.purpose))

            insight = self.brain.reflect(short_term)
            if insight:
                self.display.reflection(insight)

        self.display.warning(f"Stopped after {self.max_steps} steps (safety limit). A human must take over.")
        return None

    def _approved(self, action):
        if self.approver is None:
            self.display.approval(action.tool, None)
            return True
        ok = self.approver(action)
        self.display.approval(action.tool, ok)
        return ok

    def _learn(self, goal):
        for bucket, key, value in self.brain.lessons():
            facts = self.long_term.get(bucket, {})
            facts[key] = value
            self.long_term.set(bucket, facts)
            self.display.memory(f"learned: {bucket}[{key}] = {value}")
        self.long_term.set("alerts_handled", self.long_term.get("alerts_handled", 0) + 1)
