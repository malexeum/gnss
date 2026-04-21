import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUI_DIR = ROOT / "app" / "gui"
CORE_DIR = ROOT / "app" / "core"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(GUI_DIR) not in sys.path:
    sys.path.insert(0, str(GUI_DIR))
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from gnss_gui_v3_5_6 import main

if __name__ == "__main__":
    main()