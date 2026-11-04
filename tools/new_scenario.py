#!/usr/bin/env python3
"""Scaffold a new ZeroRange scenario.

    python3 tools/new_scenario.py hotel --title Hotel --brand "Sam Hotel" \\
        --stage ibutton:"Lobby fob" --stage mifare:"Room card" --stage custom:"Minibar"

Stage types:
  ibutton  learner touches a specific iButton UID   (IButtonMatchStage)
  mifare   PM3 emulates a badge, learner reads it   (MifareEmulationStage)
           -> a starter badge .nfc is generated with a random key
  custom   free-form stage with a run() skeleton    (Stage)

Creates challenges/<key>/ (scenario.py + one file per stage, badges/) and a
smoke test in tests/<key>/. Challenge ids are allocated after the highest id
in use. Nothing is written to config.json: defaults live in scenario.py and
can be overridden in config.json / config.local.json under "<key>".
"""

import argparse
import json
import re
import secrets
import sys
from pathlib import Path
from string import Template
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.catalog import build_catalog, next_free_ids  # noqa: E402
from app.core.nfc_file import make_mfc1k, render_nfc  # noqa: E402
from app.scenarios.registry import discover  # noqa: E402

STAGE_TYPES = ("ibutton", "mifare", "custom")
KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "stage"


def camel(text: str, limit: int) -> str:
    """"Lobby fob" -> "LobbyFob"; falls back to the first word if too long."""
    words = [w.capitalize() for w in re.split(r"[^A-Za-z0-9]+", text) if w]
    joined = "".join(words)
    if len(joined) <= limit or not words:
        return joined or "Stage"
    return words[0][:limit]


# ---------------------------------------------------------------------------
# Templates ($name placeholders — braces are literal Python)
# ---------------------------------------------------------------------------

INIT_TMPL = Template('''"""$brand — $title training scenario for ZeroRange.

DISCLAIMER: "$brand" is entirely fictional. Any resemblance to real products
or deployments is coincidental. Training in a controlled environment only.
"""
''')

SCENARIO_TMPL = Template('''"""$title scenario declaration — picked up automatically by the registry.

Validate with:  python3 tools/validate_scenarios.py
"""

from app.scenarios.base import ScenarioDef
$imports

SCENARIO = ScenarioDef(
    key="$key",
    title="$title",
    brand="$brand",
    description="TODO: one-sentence pitch shown on the web companion.",
    disclaimer=("All names are", "FICTIONAL.", "Training only."),
    stages=($stage_classes),
    complete_lines=("$complete_lcd", "COMPLETE!"),
    order=$order,
    sequential=True,        # stage N unlocks when stage N-1 is solved
    # Config defaults; override them in config.json under "$key".
    defaults=$defaults,
    # secrets=my_secrets,   # per-session random keys/UIDs: see docs/SCENARIO_GUIDE.md
)
''')

IBUTTON_TMPL = Template('''"""Stage $n — $label (iButton, $points pts)."""

from app.scenarios.stages import IButtonMatchStage


class Stage$n(IButtonMatchStage):
    challenge_id = $cid          # never renumber: progress is stored against it
    number = $n
    title = "$lcd_title"
    name = "$label"
    description = "TODO: one-line objective"
    points = $points

    hints = ("TODO: first hint (costs 2 pts)", "TODO: second, more explicit hint")

    uid_key = "stage${n}_uid"    # set the real UID in config.json["$key"]
    intro = ("$short Stage $n", "TODO: pretext")
    prompt = "Touch iButton"
    noun = "key"
    success_lines = ("Access granted!", "+${points}pts")

    def reveal(self) -> None:
        """Optional: leak the clue needed by the next stage."""
        # self.ui.show("Clue found:", self.cfg_get("stage${n}_clue", ""), hold=4)
''')

MIFARE_TMPL = Template('''"""Stage $n — $label (Proxmark3 MIFARE Classic emulation, $points pts)."""

from app.scenarios.stages import MifareEmulationStage


class Stage$n(MifareEmulationStage):
    challenge_id = $cid          # never renumber: progress is stored against it
    number = $n
    title = "$lcd_title"
    name = "$label"
    description = "TODO: one-line objective"
    points = $points

    hints = ("TODO: first hint (costs 2 pts)", "TODO: second, more explicit hint")

    badge_key = "stage${n}_badge"     # Flipper .nfc file emulated by the PM3
    key_key = "stage${n}_key_hex"     # key the learner must find / use
    key_type = "A"
    sectors = frozenset({1})          # sectors to authenticate

    intro = ("$short Stage $n", "TODO: pretext")
    instructions = (("PM3 emulates", "the card. Read!"),)
    success_lines = ("Access granted!", "+${points}pts")
''')

CUSTOM_TMPL = Template('''"""Stage $n — $label ($points pts)."""

from app.core.ui import Button
from app.scenarios.base import Stage


class Stage$n(Stage):
    challenge_id = $cid          # never renumber: progress is stored against it
    number = $n
    title = "$lcd_title"
    name = "$label"
    description = "TODO: one-line objective"
    points = $points
    requires = None              # "hid" | "proxmark" | "hackrf" | "flirc" -> self.hw
    hints = ("TODO: first hint (costs 2 pts)", "TODO: second, more explicit hint")

    def run(self) -> int:
        if self.already_complete():
            self.show_already_solved()
            return 0

        self.ui.show("$short Stage $n", "TODO: pretext", hold=2)
        self.start_timer()
        while True:
            btn = self.ui.prompt("TODO: objective", "SEL=Check ◄=Back",
                                 Button.SELECT, Button.BACK)
            if btn == Button.BACK:
                return 0
            if self.check():
                points = self.award()
                self.finish()
                return points
            self.ui.show("Not yet!", "Try again", hold=2)

    def check(self) -> bool:
        """TODO: verify what the learner did (read hardware, compare values...)."""
        return False
''')

TEST_TMPL = Template('''"""Smoke tests generated by tools/new_scenario.py — extend them!"""

import unittest

from app.core.config import load_config
from app.core.ui import Button
from app.scenarios.validate import validate_scenario
from challenges.$key.scenario import SCENARIO
from tests.fakes import make_runner


class Test${class_key}Scenario(unittest.TestCase):

    def test_no_validation_errors(self):
        errors = [i for i in validate_scenario(SCENARIO, load_config()) if i.level == "error"]
        self.assertFalse(errors, "\\n".join(map(str, errors)))

    def test_back_from_menu_exits(self):
        runner, lcd, _db = make_runner(SCENARIO, script=[Button.BACK])
        self.assertEqual(runner.run(), 0)

    def test_every_stage_can_be_opened_and_left(self):
        # SELECT opens stage N, BACK leaves it, BACK leaves the menu.
        for index, _stage in enumerate(SCENARIO.stages):
            with self.subTest(stage=index + 1):
                script = [Button.DOWN] * index + [Button.SELECT] + [Button.BACK] * 3
                runner, lcd, db = make_runner(SCENARIO, script=script, lenient=True)
                runner.run()
                db.close()


if __name__ == "__main__":
    unittest.main()
''')


# ---------------------------------------------------------------------------

def plan(args) -> Tuple[Dict[Path, str], Dict[str, object]]:
    registry = discover()
    if registry.get(args.key) or (ROOT / "challenges" / args.key).exists():
        if not args.force:
            raise SystemExit(f"challenges/{args.key} already exists (use --force to overwrite)")

    stages: List[Tuple[str, str]] = []
    for spec in args.stage or ["custom:Stage one"]:
        kind, _, label = spec.partition(":")
        kind = kind.strip().lower()
        if kind not in STAGE_TYPES:
            raise SystemExit(f"Unknown stage type {kind!r}; choose from {', '.join(STAGE_TYPES)}")
        stages.append((kind, label.strip() or kind.capitalize()))

    others = [s for s in registry.scenarios if s.key != args.key]
    ids = next_free_ids(build_catalog(others), len(stages))
    order = max([s.order for s in others] + [0]) + 10
    short = args.title[:8]
    brand = args.brand or f"Sam {args.title}"

    files: Dict[Path, str] = {}
    defaults: Dict[str, object] = {}
    pkg = ROOT / "challenges" / args.key
    imports, classes = [], []

    for n, ((kind, label), cid) in enumerate(zip(stages, ids), start=1):
        module = f"stage{n}_{slug(label)}"
        values = dict(n=n, cid=cid, label=label.replace('"', "'"), points=args.points,
                      key=args.key, short=short,
                      lcd_title=f"Stage{n}:{camel(label, 14 - len(f'Stage{n}:'))}")
        if kind == "ibutton":
            files[pkg / f"{module}.py"] = IBUTTON_TMPL.substitute(values)
            defaults[f"stage{n}_uid"] = "REPLACE_WITH_IBUTTON_UID"
        elif kind == "mifare":
            files[pkg / f"{module}.py"] = MIFARE_TMPL.substitute(values)
            key = secrets.token_bytes(6)
            badge_rel = f"challenges/{args.key}/badges/stage{n}.nfc"
            blocks = make_mfc1k(secrets.token_bytes(4), keys_a={1: key},
                                data={1: args.key.upper().encode()[:16]})
            files[ROOT / badge_rel] = render_nfc(blocks)
            defaults[f"stage{n}_badge"] = badge_rel
            defaults[f"stage{n}_key_hex"] = key.hex().upper()
        else:
            files[pkg / f"{module}.py"] = CUSTOM_TMPL.substitute(values)
        imports.append(f"from challenges.{args.key}.{module} import Stage{n}")
        classes.append(f"Stage{n}")

    defaults_src = json.dumps(defaults, indent=8).replace("\n}", "\n    }") if defaults else "{}"
    files[pkg / "__init__.py"] = INIT_TMPL.substitute(brand=brand, title=args.title)
    files[pkg / "scenario.py"] = SCENARIO_TMPL.substitute(
        key=args.key, title=args.title, brand=brand[:16],
        complete_lcd=f"{args.title.upper()[:9]} MODULE"[:16],
        imports="\n".join(imports), stage_classes=", ".join(classes) + ",",
        order=order, defaults=defaults_src)
    tests = ROOT / "tests" / args.key
    files[tests / "__init__.py"] = ""
    files[tests / f"test_{args.key}_scenario.py"] = TEST_TMPL.substitute(
        key=args.key, class_key=camel(args.key, 40))
    return files, defaults


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Scaffold a ZeroRange scenario",
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog=__doc__)
    parser.add_argument("key", help="package name, e.g. hotel (lowercase, a-z0-9_)")
    parser.add_argument("--title", help="main-menu label (<= 8 chars)")
    parser.add_argument("--brand", help="fictional brand shown in the disclaimer")
    parser.add_argument("--stage", action="append", metavar="TYPE:LABEL",
                        help=f"repeatable; TYPE in {', '.join(STAGE_TYPES)}")
    parser.add_argument("--points", type=int, default=10, help="points per stage")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    parser.add_argument("--force", action="store_true", help="overwrite an existing scenario")
    args = parser.parse_args(argv)

    if not KEY_RE.match(args.key):
        parser.error("key must match ^[a-z][a-z0-9_]*$")
    args.title = (args.title or args.key.capitalize())[:8]

    files, defaults = plan(args)
    for path, content in files.items():
        rel = path.relative_to(ROOT)
        if args.dry_run:
            print(f"would write {rel}")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"wrote {rel}")

    print(f"\nNext steps:\n"
          f"  1. Fill the TODOs in challenges/{args.key}/*.py\n"
          f"  2. Put real values in config.json under \"{args.key}\" "
          f"(defaults: {', '.join(defaults) or 'none'})\n"
          f"  3. python3 tools/validate_scenarios.py\n"
          f"  4. python3 -m pytest tests/{args.key}\n"
          f"  5. Optional: app/web/templates/scenarios/{args.key}.html for a custom web page\n"
          f"     (a generic page is served at /scenarios/{args.key}/ meanwhile)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
