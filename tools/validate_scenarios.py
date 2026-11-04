#!/usr/bin/env python3
"""Check every scenario before deploying to the Pi.

    python3 tools/validate_scenarios.py            # errors + warnings
    python3 tools/validate_scenarios.py --strict   # warnings fail too (CI)

Exit code 1 if there is any error (or any warning with --strict).
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.scenarios.registry import discover  # noqa: E402
from app.scenarios.validate import summary, validate_all  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--strict", action="store_true", help="treat warnings as errors")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.CRITICAL)  # import errors are reported below
    registry = discover()
    issues = validate_all(registry)

    print(summary(registry))
    print()
    for issue in issues:
        print(issue)
    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warning"]
    print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors or (args.strict and warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
