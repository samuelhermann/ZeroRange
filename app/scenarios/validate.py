"""Static checks for scenarios — run ``python3 tools/validate_scenarios.py``.

Catches, before anything reaches the Pi: duplicate challenge ids, labels that
do not fit on the 16x2 LCD, missing config keys, placeholder UIDs left in
config.json, badge files that do not exist...
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.catalog import CLASSIC_MODULES, build_catalog
from app.core.config import load_config, lookup
from app.core.paths import resolve
from app.scenarios.base import KNOWN_DEVICES, ScenarioDef, Stage, Tool
from app.scenarios.registry import Registry, discover

LCD = 16
STEP_TITLE_MAX = 14     # ">" + title + "✓"
MENU_TITLE_MAX = 8      # ">" + title + " 210/210"
KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class Issue:
    level: str      # "error" | "warning"
    where: str
    message: str

    def __str__(self) -> str:
        return f"[{self.level.upper():7}] {self.where}: {self.message}"


def _check_len(issues: List[Issue], where: str, label: str, text: str, limit: int) -> None:
    if len(text) > limit:
        issues.append(Issue("warning", where,
                            f"{label} {text!r} is {len(text)} chars (LCD shows {limit})"))


def validate_scenario(sc: ScenarioDef, config: Dict[str, Any]) -> List[Issue]:
    issues: List[Issue] = []
    where = f"scenario {sc.key}"

    if not KEY_RE.match(sc.key):
        issues.append(Issue("error", where, "key must match ^[a-z][a-z0-9_]*$"))
    if not sc.stages:
        issues.append(Issue("error", where, "has no stages"))
    _check_len(issues, where, "title", sc.title, MENU_TITLE_MAX)
    _check_len(issues, where, "brand", sc.brand, LCD)
    for line in sc.disclaimer:
        _check_len(issues, where, "disclaimer line", line, LCD)
    _check_len(issues, where, "complete_lines[0]", sc.complete_lines[0], LCD)
    _check_len(issues, where, "complete_lines[1]", sc.complete_lines[1], LCD - 6)

    numbers = [getattr(s, "number", 0) for s in sc.stages]
    if sorted(numbers) != list(range(1, len(sc.stages) + 1)):
        issues.append(Issue("error", where,
                            f"stage numbers must be 1..{len(sc.stages)}, got {numbers}"))

    section = sc.resolve_config(config)
    for step in sc.steps:
        sw = f"{sc.key}.{step.__name__}"
        is_stage = isinstance(step, type) and issubclass(step, Stage)
        if not (is_stage or (isinstance(step, type) and issubclass(step, Tool))):
            issues.append(Issue("error", sw, "must subclass Stage or Tool"))
            continue
        if step in sc.stages and not is_stage:
            issues.append(Issue("error", sw, "listed in stages but is not a Stage"))
        if not step.title:
            issues.append(Issue("error", sw, "title is empty"))
        _check_len(issues, sw, "title", step.title, STEP_TITLE_MAX)
        if step.requires is not None and step.requires not in KNOWN_DEVICES:
            issues.append(Issue("error", sw, f"requires {step.requires!r}; "
                                             f"known devices: {', '.join(KNOWN_DEVICES)}"))
        if is_stage:
            if not isinstance(step.challenge_id, int) or step.challenge_id <= 0:
                issues.append(Issue("error", sw, "challenge_id must be a positive int"))
            if step.points <= 0:
                issues.append(Issue("error", sw, "points must be > 0"))
            if not (step.name or step.title):
                issues.append(Issue("warning", sw, "no name for the scores DB"))

        defaults = step.defaults()
        for key in step.config_keys:
            value = lookup(section, key, None)
            if value is None:
                if not defaults.get(key):
                    issues.append(Issue("error", sw, f"config '{sc.section}.{key}' is missing "
                                                     f"and has no default"))
                continue
            if isinstance(value, str) and value.upper().startswith(("REPLACE", "TODO", "CHANGE")):
                issues.append(Issue("warning", sw, f"config '{sc.section}.{key}' is a "
                                                   f"placeholder ({value!r}); the stage "
                                                   f"cannot be solved until it is set"))
        for key in step.file_keys:
            value = lookup(section, key, None) or defaults.get(key)
            if value and not resolve(value).is_file():
                issues.append(Issue("error", sw, f"file '{value}' ({sc.section}.{key}) not found"))
    return issues


def validate_all(registry: Optional[Registry] = None,
                 config: Optional[Dict[str, Any]] = None) -> List[Issue]:
    registry = registry if registry is not None else discover()
    config = config if config is not None else load_config()
    issues: List[Issue] = [Issue("error", f"scenario {k}", f"failed to load: {e}")
                           for k, e in registry.errors.items()]

    owners: Dict[int, str] = {c.id: f"classic {m.key}" for m in CLASSIC_MODULES for c in m.challenges}
    for sc in registry:
        for stage in sc.stages:
            cid = getattr(stage, "challenge_id", None)
            label = f"{sc.key}.{stage.__name__}"
            if cid in owners:
                issues.append(Issue("error", label,
                                    f"challenge_id {cid} already used by {owners[cid]}"))
            else:
                owners[cid] = label
        issues.extend(validate_scenario(sc, config))

    titles = [m.title for m in CLASSIC_MODULES] + [s.title for s in registry]
    dupes = {t for t in titles if titles.count(t) > 1}
    for t in sorted(dupes):
        issues.append(Issue("error", "main menu", f"duplicate title {t!r}"))
    return issues


def summary(registry: Registry) -> str:
    rows = build_catalog(registry.scenarios)
    lines = [f"{len(rows)} challenges, {sum(r[4] for r in rows)} pts total"]
    for sc in registry:
        stages = ", ".join(f"#{s.challenge_id} {s.title}" for s in sc.stages)
        lines.append(f"  {sc.key:<10} {sc.max_points:>3} pts  {stages}")
    return "\n".join(lines)
