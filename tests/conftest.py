import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("BENCHY_ROOT", str(ROOT))
FIXTURES = Path(__file__).parent / "fixtures"
