"""Demo cho strategies và indicators trong Nautilus Trader."""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

from demo.demo_indicators import main

if __name__ == "__main__":
    main()
