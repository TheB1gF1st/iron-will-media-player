"""Registers Iron Will Media Player with Windows as a video player (current user only, no admin needed).
Same as Options > File Types. Windows only lets *you* pick defaults, so this opens Settings at Iron Will's page.

    E:\\PythonMedia\\python.exe tools\\register_windows.py            register video types + open Settings
    E:\\PythonMedia\\python.exe tools\\register_windows.py --audio    also audio types
    E:\\PythonMedia\\python.exe tools\\register_windows.py --remove   undo everything this added
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ironwill import associate  # noqa: E402

if __name__ == "__main__":
    if "--remove" in sys.argv:
        associate.remove()
        print("Removed Iron Will's Windows registration. (Pick another default player in Settings > Default apps.)")
    else:
        associate.register(video=True, audio="--audio" in sys.argv)
        print(f"Registered {associate.APP_NAME} for {len(associate.VIDEO_EXTS)} video types"
              + (f" and {len(associate.AUDIO_EXTS)} audio types." if "--audio" in sys.argv else "."))
        if "--no-settings" not in sys.argv:
            associate.open_default_apps()
