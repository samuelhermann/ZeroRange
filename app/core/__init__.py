"""Hardware-agnostic building blocks shared by the LCD app and the web companion.

Nothing in this package may import Flask or hardware libraries at module level:
it must stay importable on a laptop, in CI and in unit tests.
"""
