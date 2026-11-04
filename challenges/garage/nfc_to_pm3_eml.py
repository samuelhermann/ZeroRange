"""Backward-compatible alias of :mod:`app.core.nfc_file` (was a duplicate)."""

from app.core.nfc_file import (  # noqa: F401
    NfcConvertError, blocks_to_eml, eml_to_blocks, nfc_to_eml, parse_nfc,
)
