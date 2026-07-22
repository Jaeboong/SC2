from __future__ import annotations

import subprocess
import shutil
import tempfile
from pathlib import Path


def discover_sc2_executable() -> Path:
    roots = (
        Path(r"C:\Program Files (x86)\StarCraft II"),
        Path(r"C:\Program Files\StarCraft II"),
    )
    candidates: list[Path] = []
    for root in roots:
        versions = root / "Versions"
        if versions.is_dir():
            candidates.extend(versions.glob("Base*/SC2_x64.exe"))
    if not candidates:
        raise FileNotFoundError("StarCraft II SC2_x64.exe was not found")
    return max(candidates, key=lambda path: int(path.parent.name.removeprefix("Base")))


def launch_sc2(
    executable: Path,
    api_port: int,
    index: int,
    *,
    width: int = 800,
    height: int = 450,
    fullscreen: bool = False,
) -> subprocess.Popen[bytes]:
    # SC2 exits immediately when Base*/SC2_x64.exe is started with its own
    # directory as cwd. Blizzard's API launcher uses Support64 as the working
    # directory even though the executable lives below Versions/.
    data_directory = executable.parents[2]
    support_directory = data_directory / "Support64"
    temp_directory = Path(tempfile.mkdtemp(prefix=f"SC2_{api_port}_"))
    column = index % 2
    row = index // 2
    arguments = [
        str(executable),
        "-listen",
        "127.0.0.1",
        "-port",
        str(api_port),
        "-dataDir",
        str(data_directory),
        "-tempDir",
        str(temp_directory),
        "-displayMode",
        "1" if fullscreen else "0",
    ]
    if not fullscreen:
        # SC2 sizes a fullscreen client from the desktop resolution. Passing the
        # window geometry anyway makes it open at that size instead, so these
        # arguments belong to windowed mode only. Verification probes stay
        # windowed and tiled; only the launcher asks for fullscreen.
        arguments += [
            "-windowwidth",
            str(width),
            "-windowheight",
            str(height),
            "-windowx",
            str(40 + column * (width + 20)),
            "-windowy",
            str(40 + row * (height + 40)),
        ]
    try:
        process = subprocess.Popen(
            arguments,
            cwd=support_directory,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    except Exception:
        shutil.rmtree(temp_directory, ignore_errors=True)
        raise

    # Keep the unique SC2 temp directory with the process so every caller gets
    # the same cleanup behavior without needing a separate wrapper object.
    process.sc2_temp_directory = temp_directory  # type: ignore[attr-defined]
    return process


def stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    temp_directory = getattr(process, "sc2_temp_directory", None)
    if temp_directory is not None:
        shutil.rmtree(temp_directory, ignore_errors=True)
