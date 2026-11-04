import unittest

from app.core.lcd_charset import to_lcd
from app.core.ui import UI, Button, eur, hex_fit, hex_spaced, is_hex, normalize_hex
from tests.fakes import FakeClock, FakeLCD, Idle

U, D, S, B = Button.UP, Button.DOWN, Button.SELECT, Button.BACK


def ui_with(script=()):
    clock = FakeClock()
    lcd = FakeLCD(script, clock=clock)
    return UI(lcd, clock), lcd, clock


class TestFormatting(unittest.TestCase):

    def test_hex_helpers(self):
        self.assertEqual(normalize_hex("01-00:c0 ff"), "0100C0FF")
        self.assertTrue(is_hex("de ad"))
        self.assertFalse(is_hex("REPLACE_ME"))
        self.assertFalse(is_hex(""))
        self.assertEqual(hex_spaced("B4EEC0"), "B4 EE C0")

    def test_hex_fit_always_fits_16(self):
        self.assertEqual(hex_fit("B4EEC0FFEE11"), "B4EE C0FF EE11")
        self.assertEqual(hex_fit("DEADBEEF"), "DE AD BE EF")
        self.assertLessEqual(len(hex_fit("0100C0FFEE7E11AB")), 16)

    def test_eur(self):
        self.assertEqual(eur(5000), "50,00")
        self.assertEqual(eur(150), "1,50")
        self.assertEqual(eur(-5), "-0,05")


class TestLcdCharset(unittest.TestCase):

    def test_glyphs_and_substitutes(self):
        self.assertEqual(to_lcd("ok ✓"), "ok \x01")
        self.assertEqual(to_lcd("◄=Back"), "\x02=Back")
        self.assertEqual(to_lcd("hint→"), "hint\x7e")
        self.assertEqual(to_lcd("café — x"), "cafe - x")
        self.assertEqual(to_lcd("\x07"), "\x01")

    def test_everything_is_single_byte(self):
        out = to_lcd("Ünïcødé ✓◄►→←°…")
        self.assertTrue(all(ord(c) < 256 for c in out))


class TestUI(unittest.TestCase):

    def test_menu_wraps_and_selects(self):
        ui, lcd, _ = ui_with([U, S])
        self.assertEqual(ui.menu(3, lambda i: (f"item{i}", "")), 2)

    def test_menu_back_returns_none(self):
        ui, _, _ = ui_with([D, B])
        self.assertIsNone(ui.menu(3, lambda i: (f"item{i}", "")))

    def test_menu_redraws_only_on_change(self):
        ui, lcd, _ = ui_with([Idle(5), D, Idle(5), S])
        ui.menu(2, lambda i: (f"item{i}", ""))
        self.assertEqual([s[0] for s in lcd.screens], ["item0", "item1"])

    def test_wait_timeout_uses_clock(self):
        ui, _, clock = ui_with([])
        t0 = clock.now()
        self.assertIsNone(ui.wait(S, timeout=3))
        self.assertGreaterEqual(clock.now() - t0, 3)

    def test_confirm(self):
        self.assertTrue(ui_with([S])[0].confirm("q?"))
        self.assertFalse(ui_with([B])[0].confirm("q?"))

    def test_skippable_slides(self):
        ui, lcd, _ = ui_with([S])
        self.assertFalse(ui.slides("T", ["a", "b", "c"], skippable=True))
        self.assertEqual(lcd.screens, [("T", "a")])

    def test_lines_truncated_to_lcd_width(self):
        ui, lcd, _ = ui_with()
        ui.show("x" * 30, "y")
        self.assertEqual(lcd.screens[-1][0], "x" * 16)
