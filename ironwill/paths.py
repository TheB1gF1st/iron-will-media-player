"""Where Iron Will is running from: next to Iron Will.exe in the packaged release, or the project folder when run
from source. mpv (libmpv-2.dll) and FFmpeg are looked for here first."""
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent.parent
