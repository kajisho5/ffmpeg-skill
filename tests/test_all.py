#!/usr/bin/env python3
"""End-to-end tests: build synthetic footage, run every script, verify with probe.

    python3 tests/test_all.py            # or: python3 -m unittest tests/test_all.py

The cases themselves live one module per tool group -- test_analysis, test_editing, test_audio,
test_picture, test_delivery, test_orchestration -- over the fixtures in _fixtures.py. This file
imports all six so that the entry point every CI job, npm test and release_check.sh already runs
keeps running exactly the same set; each group module is also runnable on its own.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_analysis  # noqa: E402
import test_audio  # noqa: E402
import test_delivery  # noqa: E402
import test_editing  # noqa: E402
import test_orchestration  # noqa: E402
import test_picture  # noqa: E402

MODULES = (test_analysis, test_editing, test_audio, test_picture, test_delivery, test_orchestration)


def load_tests(loader, tests, pattern):
    """unittest calls this instead of scanning this module: the cases are in the six group
    modules, and naming them here keeps the set (and the order groups run in) explicit."""
    suite = unittest.TestSuite()
    for module in MODULES:
        suite.addTests(loader.loadTestsFromModule(module))
    return suite


if __name__ == "__main__":
    unittest.main(verbosity=2)
