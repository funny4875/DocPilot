"""Resource and writable paths for source and installed application."""
import os
import shutil
import sys
from pathlib import Path

RESOURCE_DIR = Path(__file__).resolve().parent
if getattr(sys, "frozen", False):
    executable = Path(sys.executable).resolve()
    if executable.name.casefold() == "docpilot-portable.exe":
        DATA_DIR = executable.parent
    else:
        DATA_DIR = Path(os.environ["LOCALAPPDATA"]) / "DocPilot"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for source in RESOURCE_DIR.glob("*.script"):
        target = DATA_DIR / source.name
        if not target.exists():
            shutil.copy2(source, target)
else:
    DATA_DIR = RESOURCE_DIR
