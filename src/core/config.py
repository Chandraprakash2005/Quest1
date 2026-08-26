import os
import sys
from pathlib import Path
import logging
import warnings

_venv_dir = Path(sys.executable).parent.parent
_nvidia_base = _venv_dir / "Lib" / "site-packages" / "nvidia"
if _nvidia_base.exists():
    for _pkg_dir in _nvidia_base.iterdir():
        if _pkg_dir.is_dir():
            for _sub in ["bin", "lib"]:
                _dll_path = _pkg_dir / _sub
                if _dll_path.exists():
                    os.environ["PATH"] = str(_dll_path) + os.pathsep + os.environ["PATH"]
                    if hasattr(os, "add_dll_directory"):
                        os.add_dll_directory(str(_dll_path))

DEFAULT_URL = ""
DEFAULT_DIALOGUE = ""
ASR_WINDOW_PAD = 3.0
COARSE_FPS = 1.0
CONFIDENCE_OK = 85
CONFIDENCE_LOW = 70
REFINE_PASS_A = 0.1
REFINE_PASS_B = 0.01
BASE_DIR = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = BASE_DIR / "output"

OUTPUT_FRAME = "output_frame.png"
OUTPUT_MANIFEST = "manifest.json"

warnings.filterwarnings("ignore", message=".*pin_memory.*")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("DialogueDetector")
