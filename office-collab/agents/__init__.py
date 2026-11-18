"""Per-role implementations for the five-agent office collaboration system.

Each module in this package is one Agent's owned functionality, kept separate
from the orchestrator. ``system.py`` only sequences the stages; the capability
belongs to the role.

Note: this package is distinct from ``openclaw-workspace/agents/<id>/``, which
holds the OpenClaw runtime workspace (identity, operating contract, skills) for
the same roles.
"""
