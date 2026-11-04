"""Well-known filesystem locations, resolved from the repository root.

Using these instead of CWD-relative paths means ZeroRange works no matter which
directory systemd (or a developer) launches it from.
"""

from pathlib import Path
from typing import Union

REPO_ROOT = Path(__file__).resolve().parents[2]
CHALLENGES_DIR = REPO_ROOT / "challenges"
RUN_DIR = REPO_ROOT / "run"
EVENTS_DIR = RUN_DIR / "events"
LOG_DIR = REPO_ROOT / "logs"
DB_PATH = REPO_ROOT / "scores.db"
#: --sim mode: its own database, and a flag file so the web process follows it.
SIM_DB_PATH = RUN_DIR / "sim_scores.db"
SIM_FLAG = RUN_DIR / "sim_mode"


def active_db_path() -> Path:
    """The database the LCD app is using right now (sim or real)."""
    return SIM_DB_PATH if SIM_FLAG.exists() else DB_PATH


def resolve(path: Union[str, Path]) -> Path:
    """Return *path* as an absolute path; relative paths are anchored at the repo root."""
    p = Path(path).expanduser()
    return p if p.is_absolute() else REPO_ROOT / p
