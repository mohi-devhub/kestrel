import sys
from pathlib import Path

CONTROL_PLANE_DIR = Path(__file__).parent.parent / "control-plane"
sys.path.insert(0, str(CONTROL_PLANE_DIR))
