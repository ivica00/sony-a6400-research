"""Paths shared by preserved research tools; no device behavior lives here."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
LEGACY_ARTIFACTS = PROJECT_ROOT / "artifacts" / "legacy"
REFERENCE_ASSETS = PROJECT_ROOT / "assets" / "reference"


def legacy_output(filename):
    LEGACY_ARTIFACTS.mkdir(parents=True, exist_ok=True)
    return str(LEGACY_ARTIFACTS / filename)
