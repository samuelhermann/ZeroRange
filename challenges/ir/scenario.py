"""Infrared module — picked up automatically by the registry."""

from app.scenarios.base import ScenarioDef
from challenges.ir.stages import Detect, Protocols, Replay

SCENARIO = ScenarioDef(
    key="ir",
    title="IR",
    description="Infrared remotes: detect, learn & replay, identify protocols.",
    stages=(Detect, Replay, Protocols),
    complete_lines=("IR MODULE", "COMPLETE!"),
    order=5,
)
