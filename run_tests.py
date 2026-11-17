"""Run the full test suite: python run_tests.py"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

if __name__ == "__main__":
    suite = unittest.defaultTestLoader.discover(os.path.join(ROOT, "tests"))
    res = unittest.TextTestRunner(verbosity=1).run(suite)
    sys.exit(0 if res.wasSuccessful() else 1)
