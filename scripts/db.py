#!/usr/bin/env python3
"""Database maintenance entry point (delegates to backend/scripts/db.py).

    python scripts/db.py migrate
    python scripts/db.py status
    python scripts/db.py verify

3.0.0 never migrates data at startup: structural changes are applied by a human
or CI through this explicit command.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

runpy.run_path(str(BACKEND / "scripts" / "db.py"), run_name="__main__")
