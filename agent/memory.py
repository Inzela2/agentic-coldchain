"""
MEMORY: what the agent knows.

Short-term memory = evidence gathered for ONE alert (every step and result).
                    The diagnosis is built from it.
Long-term memory  = lessons kept BETWEEN alerts and runs (agent_memory.json).
                    Example: "Eastfield Hub accepted a diversion on the Riverside route",
                    "truck T-03's sensor gave a false alarm". Next time the agent
                    tries the store that worked first.
"""
import json
import os
from dataclasses import dataclass, field


@dataclass
class Step:
    thought: str
    tool: str
    args: dict
    observation: str
    is_error: bool = False
    purpose: str = ""  # investigate | act | verify | notify | report


@dataclass
class ShortTermMemory:
    steps: list = field(default_factory=list)

    def add(self, step):
        self.steps.append(step)

    def last(self):
        return self.steps[-1] if self.steps else None

    def find(self, tool):
        """First successful observation from a tool, or ''."""
        for s in self.steps:
            if s.tool == tool and not s.is_error:
                return s.observation
        return ""


class LongTermMemory:
    def __init__(self, path):
        self.path = path
        self.data = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                self.data = json.load(f)

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
