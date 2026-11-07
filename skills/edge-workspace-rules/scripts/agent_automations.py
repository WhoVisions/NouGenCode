"""
NodeWorker Agent-Layer Automations.

Parameterized adapter inheriting core logic from edge-agent-automations
to eliminate code duplication while preserving NodeWorker workspace targeting.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add shared skills directory to path
SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR / "edge-agent-automations" / "scripts"))

from edge_agent_automations import VeilVerseAutomator as _BaseAutomator


class VeilVerseAutomator(_BaseAutomator):
    """VeilVerseAutomator bound specifically to the NodeWorker configuration root."""

    def __init__(self) -> None:
        super().__init__(node_dir="NodeWorker")


if __name__ == "__main__":
    automator = VeilVerseAutomator()
    automator.run_universe_checks()
    automator.run_ingestion_checks()
