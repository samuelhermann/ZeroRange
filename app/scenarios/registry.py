"""Auto-discovery of scenarios.

Any package ``challenges/<key>/`` that contains a ``scenario.py`` defining
``SCENARIO = ScenarioDef(...)`` is picked up.  A broken scenario is logged and
skipped — it must never take the whole training box down.
"""

import importlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from app.core.paths import CHALLENGES_DIR
from app.scenarios.base import ScenarioDef

logger = logging.getLogger(__name__)


@dataclass
class Registry:
    scenarios: List[ScenarioDef] = field(default_factory=list)
    errors: Dict[str, str] = field(default_factory=dict)

    def get(self, key: str) -> Optional[ScenarioDef]:
        return next((s for s in self.scenarios if s.key == key), None)

    def keys(self) -> List[str]:
        return [s.key for s in self.scenarios]

    def __iter__(self):
        return iter(self.scenarios)

    def __len__(self):
        return len(self.scenarios)


def discover(root: Path = CHALLENGES_DIR, package: str = "challenges") -> Registry:
    registry = Registry()
    if not root.is_dir():
        logger.warning("Scenario directory not found: %s", root)
        return registry

    for child in sorted(root.iterdir()):
        if not (child / "scenario.py").is_file() or child.name.startswith(("_", ".")):
            continue
        module_name = f"{package}.{child.name}.scenario"
        try:
            module = importlib.import_module(module_name)
            scenario = getattr(module, "SCENARIO")
            if not isinstance(scenario, ScenarioDef):
                raise TypeError("SCENARIO must be a ScenarioDef instance")
            if scenario.key != child.name:
                raise ValueError(f"SCENARIO.key {scenario.key!r} must match folder {child.name!r}")
        except Exception as exc:
            logger.error("Scenario %s failed to load: %s", child.name, exc, exc_info=True)
            registry.errors[child.name] = f"{type(exc).__name__}: {exc}"
            continue
        registry.scenarios.append(scenario)

    registry.scenarios.sort(key=lambda s: (s.order, s.key))
    logger.info("Discovered %d scenario(s): %s", len(registry), ", ".join(registry.keys()))
    return registry


_default: Optional[Registry] = None


def get_registry(refresh: bool = False) -> Registry:
    """Process-wide cached registry."""
    global _default
    if _default is None or refresh:
        _default = discover()
    return _default
