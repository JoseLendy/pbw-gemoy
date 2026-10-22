"""Screenshot helper for the Vue UI: drives the headless Chromium already on this machine with its built-in
--screenshot flag (no Playwright package needed). Tabs are selected via a URL hash the app reads.

Usage: python eval/shoot.py <out_dir> [base_url]   (default http://127.0.0.1:7862)
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

CHROME = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright" / "chromium_headless_shell-1223" / \
    "chrome-headless-shell-win64" / "chrome-headless-shell.exe"
if not CHROME.is_file():
    CHROME = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright" / "chromium-1223" / "chrome-win64" / "chrome.exe"

SHOTS = [
    ("01-store-S01", "store", "S01", 1920, 1080),
    ("02-store-S04", "store", "S04", 1920, 1080),
    ("03-store-S08", "store", "S08", 1920, 1080),
    ("04-store-S10", "store", "S10", 1920, 1080),
    ("05-store-S03", "store", "S03", 1920, 1080),
    ("06-mobile", "mobile", "", 1920, 1080),
    ("07-compare", "compare", "", 1920, 1080),
    ("08-hq", "hq", "", 1920, 1080),
    ("09-baseline", "baseline", "", 1920, 1080),
    ("10-manual", "manual", "", 1920, 1080),
    ("11-store-phone", "store", "S01", 390, 844),
]


def shoot(out: Path, base: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, tab, store, w, h in SHOTS:
        url = f"{base}/#tab={tab}" + (f"&store={store}" if store else "") + "&shot=1"
        png = out / f"{name}.png"
        cmd = [str(CHROME), "--headless", "--disable-gpu", "--hide-scrollbars", "--no-proxy-server",
               f"--window-size={w},{h}", "--virtual-time-budget=9000", "--run-all-compositor-stages-before-draw",
               f"--screenshot={png}", url]
        t0 = time.time()
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        ok = png.is_file() and png.stat().st_size > 1000
        print(f"{name:18s} {'ok ' if ok else 'FAIL'} {time.time() - t0:5.1f}s {png.stat().st_size if ok else r.stderr[-200:]}")


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "eval/ui_screens/after")
    base = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:7862"
    shoot(out, base)
