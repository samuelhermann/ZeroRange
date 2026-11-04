"""Stage 3 — Top Up the Balance (value-block forgery, 10 pts).

The learner presents a forged MIFARE Classic 1K badge (magic card or Flipper
emulation) whose value block (block 40 by default) is structurally valid and
decodes to at least the configured threshold (default 5000 cents = 50,00 EUR).
"""

import logging
from typing import Optional, Tuple

from app.core.ui import eur
from app.scenarios.base import Stage
from challenges.coffee import DEFAULT_KEY_B
from challenges.coffee.value_block import ValueBlockError, decode, validate

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 5000
DEFAULT_BLOCK = 40


class Stage3(Stage):
    challenge_id = 18
    number = 3
    title = "Stage3:Refill"
    name = "Top Up Balance"
    description = "Forge value block >=50 EUR"
    requires = "proxmark"
    config_keys = ("master_key_b_hex", "credit_threshold_cents", "value_block_addr")
    hints = (
        "Credit is a MIFARE value block in block 40: value, ~value, value, addr, ~addr, addr, ~addr.",
        "Compare the 1,50 and 50,00 EUR badges (Prep Badges): value = cents, little-endian.",
    )

    @classmethod
    def defaults(cls):
        return {"master_key_b_hex": DEFAULT_KEY_B,
                "credit_threshold_cents": DEFAULT_THRESHOLD,
                "value_block_addr": DEFAULT_BLOCK}

    # ------------------------------------------------------------------ helpers

    def threshold(self) -> int:
        return int(self.cfg_get("credit_threshold_cents", DEFAULT_THRESHOLD))

    def block_addr(self) -> int:
        return int(self.cfg_get("value_block_addr", DEFAULT_BLOCK))

    def read_value_block(self) -> Tuple[Optional[bytes], str]:
        """Return ``(raw16, "")`` or ``(None, reason)``."""
        key = bytes.fromhex(self.cfg_hex("master_key_b_hex", DEFAULT_KEY_B))
        try:
            return self.hw.read_block(self.block_addr(), key, "B"), ""
        except Exception as exc:
            logger.warning("PM3 read_block error: %s", exc)
            return None, "auth_failed" if "Auth" in type(exc).__name__ else "read_failed"

    @staticmethod
    def lcd_reason(error: ValueBlockError) -> str:
        reason = str(error)
        if "Bad ~V" in reason:
            return "Bad ~V"
        if "Bad addr" in reason:
            return "Bad addr"
        return reason[:14]

    # ------------------------------------------------------------------ flow

    def run(self) -> int:
        if self.already_complete():
            self.show_already_solved()
            return 0

        if not self.require_hardware("Proxmark3 needed", "Not detected! ◄"):
            return 0

        threshold = self.threshold()
        self.ui.show("Coffee Stage 3", "Refill your card", hold=2)
        self.ui.show(f"Need >={eur(threshold)} EUR", "Present to PM3", hold=2)
        self.start_timer()

        while True:
            if not self.ui.confirm("Hold card to PM3", "SEL=Read ◄=Back"):
                return 0

            self.ui.show(f"Reading block {self.block_addr()}", "Please wait...")
            raw, error = self.read_value_block()
            if raw is None:
                if error == "auth_failed":
                    self.ui.show("Auth failed!", "Need Key B badge")
                else:
                    self.ui.show("Read failed!", "Hold card still")
                self.emit(event="credit_observed", value_cents=None, error=error)
                self.ui.sleep(3)
                continue

            try:
                validate(raw)
            except ValueBlockError as exc:
                reason = self.lcd_reason(exc)
                logger.info("Stage 3 invalid block: %s | raw=%s", exc, raw.hex())
                self.emit(event="credit_observed", value_cents=None, error=reason)
                self.ui.show("Invalid block!", reason, hold=3)
                continue

            value = decode(raw)
            logger.info("Stage 3 value=%s cents (threshold=%s)", value, threshold)
            self.emit(event="credit_observed", value_cents=value)

            if value < threshold:
                self.ui.show("Value too low!", f"{eur(value)} < {eur(threshold)}", hold=3)
                continue

            points = self.award()
            self.ui.show(f"TOPPED UP! +{points}pt", f"{eur(value)} EUR OK!", hold=3)
            self.finish("Congratulations!")
            return points
