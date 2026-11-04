# Trainer guide

Everything a trainer needs to run a group session on ZeroRange: players,
fresh secrets, the web dashboard, exports and the hardware-free simulator.

---

## Before the group arrives

1. Power on the box. The LCD home screen shows its IP address.
2. **Settings > Web login** shows the dashboard credentials
   (`trainer` + a password generated on first boot and stored in
   `run/trainer_password`). To choose your own, set it in `config.local.json`:
   ```json
   { "web": { "trainer_password": "pick-something-long" } }
   ```
   or export `ZERORANGE_TRAINER_PASSWORD` for the web service.
3. Open `http://<box-ip>:8080/dashboard/` and log in.
4. **New session** (dashboard, or LCD Settings > New session): every scenario
   that supports it gets fresh secrets — new Coffee Key B, new Garage tech-room
   key and rolling remote, new "Emulate Specific" iButton ID. Badges and `.sub`
   captures are regenerated; download them from the dashboard if you hand them
   out. Tick *also reset all scores* to start from zero.
   Physical tokens (Coffee technician iButton, Garage fob) keep the UIDs from
   `config.json`.
5. Add one **player** per learner or team (dashboard *Add player*, or LCD
   Settings > Player > *+ New player*, then rename it on the dashboard).

## During the session

- The **active player** is the one scoring on the LCD. Switch it from the
  dashboard (*Play*) or the LCD (Settings > Player). The web pages and the LCD
  main menu always show the active player's score.
- **Hints**: learners press **►** inside a stage. Each new hint costs 2 points
  (never more than half of the stage); the dashboard shows hints used.
- **Sequential scenarios** (Coffee, Garage): stage N unlocks when N-1 is solved
  (🔒 on the LCD). Disable per scenario with `"coffee": {"sequential": false}`.
- **Partial credit**: Garage Stage 1a is worth 3 points on its own; the
  learner can come back later and go straight to 1b.
- Learner pages: `http://<box-ip>:8080/` (live animations per scenario).

## After the session

- **Leaderboard**: dashboard, or LCD Settings > Leaderboard.
- **Export CSV**: one line per player and challenge (points, time, hints).
- **Certificate**: printable page per player (*Print / save as PDF*).
- **Reset** a player, or delete it with its history.

---

## Security notes

- The dashboard requires Basic auth and a CSRF token on every action. The box
  usually runs on its own Wi-Fi hotspot over plain HTTP: use a password that is
  not reused anywhere else.
- The web LCD remote (`web_lcd_server.py`, port 5000) only answers browsers on
  the box's own pages (ports 8000/8080). Make it read-only with
  `"web": {"lcd_remote_control": false}`; allow other origins with
  `"web": {"lcd_api_origins": ["http://my-host:1234"]}`.
- The Garage debug button (*send press*) requires the trainer login.

---

## Simulation mode (no hardware)

Prepare a session, rehearse a scenario or write a new one on any computer:

```bash
pip3 install -r requirements-dev.txt
python3 zerorange.py --sim              # the LCD is drawn in this terminal
python3 app/web/wsgi.py                 # optional: web pages + dashboard on :8080
```

Keys: arrows (or W/A/S/D) to move, Enter = SELECT, ← / Esc = BACK, → = hints,
Ctrl-C to quit. Scores go to `run/sim_scores.db`, never to the real database.

Play the learner from another terminal, or from the dashboard's *Simulator*
panel (shown while `--sim` runs):

```bash
python3 tools/sim_inject.py ibutton 0100C0FFEE7E11AB          # touch the reader
python3 tools/sim_inject.py nfc 04A3F5B2                       # card on the PM3
python3 tools/sim_inject.py rfid 1122334455 --type EM410x
python3 tools/sim_inject.py rf --strength -40                  # Sub-GHz press
python3 tools/sim_inject.py ir KEY_POWER --protocol NEC
python3 tools/sim_inject.py pm3-log "Auth sector 8 key B B4EEC0FFEE11"
python3 tools/sim_inject.py pm3-card challenges/coffee/badges/credit_high.nfc
```

The simulated Proxmark3 checks MIFARE keys against the badge it emulates, so
"SEL = I'm done" in a MIFARE stage behaves like the real verification.
