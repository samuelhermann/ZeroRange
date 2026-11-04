"""iButton module — picked up automatically by the registry."""

from app.core.session import random_ds1990_uid
from app.scenarios.base import ScenarioDef
from challenges.ibutton.stages import Clone, EmulateTarget, TouchRead


def secrets(rng, config, out_dir):
    """New session: a fresh target ID for "Emulate Specific"."""
    return {"ch3_target_uid": random_ds1990_uid(rng)}


SCENARIO = ScenarioDef(
    key="ibutton",
    title="iButton",
    description="Dallas 1-Wire keys: read, clone and emulate DS1990A iButtons.",
    stages=(TouchRead, Clone, EmulateTarget),
    complete_lines=("IBUTTON MODULE", "COMPLETE!"),
    order=1,
    secrets=secrets,
)
