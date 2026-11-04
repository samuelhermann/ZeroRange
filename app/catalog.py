"""Single source of truth for every scored challenge.

Every module — the fundamentals (iButton, NFC, RFID, SubGHZ, IR) and the
themed scenarios (Coffee, Garage, ...) — is a scenario declared in
``challenges/<key>/scenario.py``. ``build_catalog`` turns them into the rows
the database is synced with at boot.
"""

from typing import Iterable, List, Tuple

CatalogRow = Tuple[int, str, str, str, int]  # id, module, name, description, points


def build_catalog(scenarios: Iterable = ()) -> List[CatalogRow]:
    rows: List[CatalogRow] = []
    for scenario in scenarios:
        rows.extend(scenario.catalog_rows())
    return sorted(rows)


def next_free_ids(rows: Iterable[CatalogRow], count: int) -> List[int]:
    """Allocate *count* consecutive ids after the highest one in use."""
    start = max((r[0] for r in rows), default=0) + 1
    return list(range(start, start + count))
