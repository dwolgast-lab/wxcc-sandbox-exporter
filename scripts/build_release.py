#!/usr/bin/env python3
"""Build a standalone executable and package it with the docs.

    pip install pyinstaller
    python scripts/build_release.py

Produces dist/wxcc-export-<version>-<platform>.zip containing the executable
(no Python needed to run it), the user docs, .env.example and the license.

PyInstaller cannot cross-compile: run this once per OS. The GitHub Actions
release workflow runs it on each OS in its matrix (currently Windows).
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wxcc_export import __version__  # noqa: E402

# Shipped next to the executable, paths preserved so the docs' relative links
# still resolve inside the zip.
DOCS = ["README.md", "CHANGELOG.md", "LICENSE", ".env.example",
        "docs/user-guide.md", "docs/api-notes.md"]


def platform_tag() -> str:
    osname = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    arch = platform.machine().lower()
    arch = {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64"}.get(arch, arch)
    return f"{osname}-{arch}"


def main() -> int:
    build = ROOT / "build"
    dist = ROOT / "dist"
    shutil.rmtree(build, ignore_errors=True)
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--onefile", "--console", "--name", "wxcc-export",
         "--paths", str(ROOT / "src"),
         "--collect-submodules", "wxcc_export",
         "--add-data",
         f"{ROOT / 'src/wxcc_export/web/static'}{os.pathsep}wxcc_export/web/static",
         "--distpath", str(dist), "--workpath", str(build),
         "--specpath", str(build),
         str(ROOT / "wxcc-export.py")],
        check=True, cwd=ROOT)

    exe = dist / ("wxcc-export.exe" if sys.platform == "win32" else "wxcc-export")
    out = subprocess.run([str(exe), "--version"], capture_output=True, text=True,
                         check=True).stdout.strip()
    if __version__ not in out:
        raise SystemExit(f"built binary reports {out!r}, expected {__version__}")

    zpath = dist / f"wxcc-export-{__version__}-{platform_tag()}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        info = zipfile.ZipInfo(
            exe.name, time.localtime(exe.stat().st_mtime)[:6])
        info.external_attr = 0o755 << 16          # keep it executable on unzip
        info.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(info, exe.read_bytes())
        for rel in DOCS:
            z.write(ROOT / rel, rel)
    print(f"built {zpath.relative_to(ROOT)} ({out})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
