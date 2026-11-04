# Creating a ZeroRange scenario

A **scenario** is a themed chain of scored **stages** (plus optional unscored
**tools**) around a fictional target: a coffee machine, a car park, a hotel...
Coffee and Garage are scenarios. Since v1.1 a scenario is *declared* in one
folder; the framework provides everything else:

| You write | The framework provides |
|-----------|------------------------|
| `challenges/<key>/scenario.py` (a `ScenarioDef`) | Main-menu entry, disclaimer, stage menu with ✓ and score |
| One small class per stage | Scores DB rows (synced at boot), timing, history |
| Config defaults | `config.json` / `config.local.json` overrides |
| (optional) a web template | Generic web page, live SSE events, `/api/status` |
| | Hardware injection (`hid`, `proxmark`, `hackrf`), "device missing" screens |
| | Crash isolation: a failing stage never takes the box down |
| | `tools/validate_scenarios.py` static checks |

---

## 1. Scaffold

```bash
python3 tools/new_scenario.py hotel --title Hotel --brand "Sam Hotel" \
    --stage ibutton:"Lobby fob" \
    --stage mifare:"Room card" \
    --stage custom:"Minibar"
```

This creates:

```
challenges/hotel/
├── __init__.py              # disclaimer docstring
├── scenario.py              # ScenarioDef + config defaults
├── stage1_lobby_fob.py      # IButtonMatchStage
├── stage2_room_card.py      # MifareEmulationStage
├── stage3_minibar.py        # custom Stage with a run() skeleton
└── badges/stage2.nfc        # starter MIFARE 1K badge, random key in sector 1
tests/hotel/test_hotel_scenario.py
```

Challenge ids are allocated after the highest id in use (`--dry-run` shows the
plan). Reboot the LCD app and the web companion: **Hotel** appears in the main
menu and at `http://<pi>:8080/scenarios/hotel/`.

## 2. Fill the TODOs, then validate

```bash
python3 tools/validate_scenarios.py      # add --strict in CI
python3 -m pytest tests/hotel
```

The validator reports, among others:

- duplicate `challenge_id` (with classic modules or other scenarios);
- labels that do not fit the 16x2 LCD (stage titles ≤ 14, menu title ≤ 8);
- stage numbers that are not `1..N`;
- unknown hardware names;
- config keys that are missing (and have no default) or still a placeholder
  (`REPLACE_...`, `TODO...`) — the stage would be unsolvable;
- badge / data files that do not exist.

---

## Stage types

All stages share the constructor `(lcd, db, config, hw, sse_emit, *, clock)`;
you never call it yourself, the runner does.

### `IButtonMatchStage` — touch a specific iButton

```python
from app.core.ui import hex_fit
from app.scenarios.stages import IButtonMatchStage

class Stage1(IButtonMatchStage):
    challenge_id = 22            # never renumber once deployed
    number = 1
    title = "Stage1:Lobby"       # <= 14 chars
    name = "Lobby fob"
    description = "Clone the night porter's fob"

    uid_key = "lobby_uid"        # config key holding the expected UID
    intro = ("Hotel Stage 1", "Night porter...")
    prompt = "Touch iBtn fob"
    noun = "fob"                 # "No fob seen", "Wrong fob!"
    success_lines = ("Door unlocked!", "+10pts")

    def reveal(self):            # optional clue for the next stage
        code = self.cfg_hex("safe_code")
        self.ui.show("Note on desk:", hex_fit(code), hold=4)
        self.emit(event="clue_leaked", code=code)
```

Handles: countdown, BACK, timeout → retry prompt, wrong-UID streaks, missing
reader, unset/placeholder UID, "already solved" (replays `reveal()`).

### `MifareEmulationStage` — PM3 emulates a badge, learner authenticates

```python
class Stage2(MifareEmulationStage):
    ...
    badge_key = "room_badge"         # path to a Flipper .nfc (MIFARE Classic 1K)
    key_key = "room_key_hex"
    key_type = "A"
    sectors = frozenset({1, 2})
    instructions = (("PM3 emulates", "room card. Read!"),)
```

Completion is auto-detected from the `hf mf sim` log (lines mentioning the key
and `sector N` / `block N`; failures ignored), or with SELECT: the PM3 then reads
the first block of every target sector with the key. Override
`detect_sectors(lines)` or `verify()` for other rules.

### `BadgeEmulatorTool` — unscored "prep" helper

```python
class PrepCards(BadgeEmulatorTool):
    title = "Prep Cards"
    badges = (("Guest card", "room_badge", "challenges/hotel/badges/stage2.nfc"),)
    key_key = "room_key_hex"       # SELECT toggles it on screen
```

Add it to `ScenarioDef(tools=(PrepCards,))`.

### Custom `Stage`

```python
from app.core.ui import Button
from app.scenarios.base import Stage

class Stage3(Stage):
    challenge_id = 24
    number = 3
    title = "Stage3:Minibar"
    requires = "proxmark"          # "hid" | "proxmark" | "hackrf" -> self.hw

    def run(self) -> int:
        if self.already_complete():
            self.show_already_solved()
            return 0
        if not self.require_hardware("Proxmark3 needed"):
            return 0
        self.start_timer()
        while True:
            if not self.ui.confirm("Badge on PM3?", "SEL=Read ◄=Back"):
                return 0
            if self.check():
                points = self.award()      # DB + history + web events
                self.finish()              # "Stage 3 done! ◄=Back to menu"
                return points
            self.ui.show("Not yet!", "Try again", hold=2)
```

Building blocks available on every stage:

| Helper | Purpose |
|--------|---------|
| `self.ui.show(l0, l1, hold=s)` | write both LCD rows (truncated to 16) |
| `self.ui.slides(title, lines, hold, skippable)` | story screens |
| `self.ui.confirm(l0, l1)` | SELECT → True, BACK → False |
| `self.ui.wait(*buttons, timeout=)` / `poll(*buttons)` | blocking / non-blocking input (always waits for release) |
| `self.ui.menu(count, render)` / `choose(labels)` | scrollable list |
| `self.ui.notice(l0, l1)` | message, wait for BACK |
| `self.cfg_get("a.b", default)` / `cfg_hex` / `cfg_path` | config access (paths resolved from repo root) |
| `self.emit(event="x", ...)` | event for the web companion |
| `self.award(*extra_events)` | persist success, emit `status: success` + `stage_complete` |
| `hex_fit`, `eur`, `normalize_hex` (`app.core.ui`) | LCD-friendly formatting |

Use `self.ui.sleep()` / `self.ui.now()` rather than `time.*`: tests then run
instantly with a fake clock.

---

## Configuration

```python
SCENARIO = ScenarioDef(
    key="hotel", ...,
    defaults={"lobby_uid": "REPLACE_WITH_IBUTTON_UID",
              "room_badge": "challenges/hotel/badges/stage2.nfc"},
)
```

Effective config = `defaults` ⟵ `config.json["hotel"]` ⟵ `config.local.json["hotel"]`
(deep-merged). `config.local.json` is git-ignored: keep the real UIDs of your
own kit there.

Global: `settings.hid_device` forces the iButton HID input device
(default: auto-detect).

---

## Web companion

Every scenario gets, under `/scenarios/<key>/`:

- `/` — `app/web/templates/scenarios/<key>.html` if it exists, otherwise a
  generic page listing stages, live progress and an event log;
- `/events` — Server-Sent Events;
- `/api/status` — `{stages: [{number, name, completed, ...}], score, max_points}`.

Events travel from the LCD process to the web process through
`run/events/<key>.jsonl` (see `app/core/events.py`), so the two systemd
services stay independent. Standard events: `session_start`,
`{stage, status: "success", points}`, `stage_complete`, `scenario_complete`,
`stage_error`, plus whatever your stages `emit()`.

Scenario-specific routes: create `app/web/routes/<key>.py` with
`def extend(bp): ...` (see `routes/garage.py`). Static assets go in
`app/web/static/scenarios/<key>/` (`logo.svg` is shown on the index page).

---

## Testing

`tests/fakes.py` provides `FakeLCD` (scripted button presses, records
screens), `FakeClock`, `FakeHID`, `FakePM3`, `FakeHackRF`, plus
`make_stage()` / `make_runner()`:

```python
from app.core.ui import Button
from tests.fakes import FakeHID, Idle, make_stage

def test_correct_fob():
    stage, lcd, db, events = make_stage(
        Stage1, script=[Button.BACK], config={"lobby_uid": "01AB"},
        hw=FakeHID(["01-AB"]))
    assert stage.run() == 10
    assert lcd.saw("Door unlocked!")

def test_timeout():
    # Idle(61): press nothing for 61 s of fake time, then BACK
    stage, lcd, *_ = make_stage(Stage1, script=[Idle(61), Button.BACK],
                                config={"lobby_uid": "01AB"}, hw=FakeHID())
    stage.run()
    assert lcd.saw("No fob seen")
```

A script entry is consumed the first time the code polls that button; if the
code waits for something the script never provides, `ScriptStalled` is raised
with the last screen — no hanging test.

---

## Rules of thumb

- **Never renumber** a deployed `challenge_id`: progress is stored against it.
  Moving an id to another module resets its progress (logged at boot).
- Keep the brand fictional and say so in the disclaimer.
- Each stage should leak what the next one needs (key, code, UID): it makes
  the chain feel like a real engagement.
- Prefer auto-detection plus a SELECT "I'm done" fallback that re-verifies with
  hardware: learners never get stuck on a missed log line.
