"""Run directly from a checkout without an editable installation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from market_research.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
