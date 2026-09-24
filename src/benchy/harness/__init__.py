from .claude import ClaudeHarness
from .copilot import CopilotHarness
from .mock import MockHarness, NoopHarness, ProbeHarness

HARNESSES = {h.name: h for h in (CopilotHarness, ClaudeHarness, MockHarness, NoopHarness, ProbeHarness)}


def get(name: str):
    try:
        return HARNESSES[name]()
    except KeyError:
        raise SystemExit(f"unknown harness {name!r}; known: {', '.join(HARNESSES)}")
