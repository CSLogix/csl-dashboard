"""Shared test fixtures for CSL Dashboard tests."""
import sys
import os

# Add project root and csl-doc-tracker to path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "csl-doc-tracker"))
