from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def main() -> None:
    project_dir = Path(__file__).resolve().parent
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        "XMiniICCIDReader",
    ]
    if sys.platform == "darwin":
        # A normal .app bundle is compatible with macOS signing/notarization.
        command.extend(["--onedir", "--osx-bundle-identifier", "com.xmini.iccid-reader"])
    else:
        command.append("--onefile")
    command.append(str(project_dir / "run_gui.py"))
    subprocess.run(command, cwd=project_dir, check=True)


if __name__ == "__main__":
    main()
