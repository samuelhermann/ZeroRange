"""Backward-compatible alias of :mod:`app.core.nfc_file`.

Usage:
  python3 -m challenges.coffee.nfc_to_pm3_eml input.nfc output.eml
"""

import sys

from app.core.nfc_file import (  # noqa: F401
    NfcConvertError, blocks_to_eml, eml_to_blocks, nfc_to_eml, parse_nfc,
)

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} input.nfc output.eml", file=sys.stderr)
        sys.exit(1)
    nfc_to_eml(sys.argv[1], sys.argv[2])
    print(f"Converted {sys.argv[1]} -> {sys.argv[2]}")
