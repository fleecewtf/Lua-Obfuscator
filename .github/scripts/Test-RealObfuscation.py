"""Exercise the released app's real Lua and Luau UI workflow on a disposable runner."""

from __future__ import annotations

import os
import runpy
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def run_case(window, application, folder: Path, target: str, suffix: str, source: str) -> None:
    input_path = folder / f"sample-{target.lower().replace(' ', '-')}{suffix}"
    input_path.write_text(source, encoding="utf-8")
    window.set_source_file(input_path)
    window.target_dropdown.select(target)
    window.level_dropdown.select("Low")
    window.start_obfuscation()
    if not window.running:
        raise AssertionError(f"{target} did not start: {window.log_box.toPlainText()}")

    deadline = time.monotonic() + 120
    while window.running and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.02)
    application.processEvents()
    if window.running:
        window.cancel_obfuscation()
        raise AssertionError(f"{target} timed out.")
    if window.status_label.text() != "Done":
        raise AssertionError(
            f"{target} failed with status {window.status_label.text()}: "
            f"{window.log_box.toPlainText()}"
        )

    output = window.output_file
    if output is None or not output.is_file() or output.stat().st_size < 1:
        raise AssertionError(f"{target} produced no valid output.")
    if input_path.read_text(encoding="utf-8") != source:
        raise AssertionError(f"{target} changed the original input.")
    if output.read_bytes() == input_path.read_bytes():
        raise AssertionError(f"{target} did not transform the source.")
    if target == "Lua 5.4":
        result = subprocess.run(
            [str(window.lua_path), "-E", str(output)],
            cwd=folder,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=20,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode != 0 or "fleece-lua-smoke" not in result.stdout:
            raise AssertionError(
                f"Released Lua output did not execute correctly: {result.stdout}"
            )
    print(f"Real app workflow passed: {target}; output bytes={output.stat().st_size}")


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: Test-RealObfuscation.py RELEASE_ROOT")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    release_root = Path(sys.argv[1]).resolve(strict=True)
    app_path = release_root / "Lua Obfuscator.pyw"
    if not app_path.is_file():
        raise FileNotFoundError(app_path)
    namespace = runpy.run_path(str(app_path), run_name="fleece_release_workflow")
    application = namespace["QApplication"].instance() or namespace["QApplication"]([])
    window = namespace["LuaObfuscator"]()
    try:
        with tempfile.TemporaryDirectory(prefix="real-smoke-", dir=release_root / ".runtime") as directory:
            folder = Path(directory)
            run_case(
                window,
                application,
                folder,
                "Lua 5.4",
                ".lua",
                'print("fleece-lua-smoke")\n',
            )
            run_case(
                window,
                application,
                folder,
                "Roblox Luau",
                ".luau",
                'local message: string = "fleece-luau-smoke"\nprint(message)\n',
            )
    finally:
        window.close()
        application.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
