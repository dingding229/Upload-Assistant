#!/usr/bin/env python3
# Upload Assistant © 2025 Audionut & wastaken7 — Licensed under UAPL v1.0
import os
import platform
import shutil
from pathlib import Path
from typing import Optional, Union

try:
    from src.console import console
except ImportError:
    class SimpleConsole:
        def print(self, message: str, markup: bool = False) -> None:  # noqa: ARG002
            print(message)

    console = SimpleConsole()


def get_bdinfo_jobs() -> int:
    """Return the maximum logical CPU count available to the current process."""
    try:
        jobs = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        jobs = os.cpu_count() or 1
    return max(1, jobs)


def build_bdinfo_command(executable: str, disc_path: str, jobs: Optional[int] = None) -> list[str]:
    """Build the bdinfo report command used for BDMV scans."""
    return [
        executable,
        "--report",
        "--no-mmap",
        "--debug",
        "--jobs",
        str(get_bdinfo_jobs() if jobs is None else max(1, jobs)),
        disc_path,
    ]


class BDInfoBinaryManager:
    """Resolve the bdinfo executable used for BDMV scans.

    The scanner executable is kept separate from the Python code. We only
    resolve it here; scanning is performed by
    ``src.discparse`` with the project's report-mode command line.
    """

    @staticmethod
    async def ensure_bdinfo_binary(base_dir: Union[str, Path], debug: bool, version: str = "") -> str:  # noqa: ARG004
        """Return the bdinfo executable available on this host.

        ``BDINFO_PATH`` may be used to point at a locally installed build.
        Otherwise the bundled Linux x64 executable at ``bin/bdinfo/bdinfo`` is preferred, followed
        by ``bdinfo`` on ``PATH``.  No automatic downloader is used.
        """
        del version
        base = Path(base_dir)
        candidates: list[Path] = []
        configured = os.environ.get("BDINFO_PATH")
        if configured:
            candidates.append(Path(configured).expanduser())

        # The bundled release asset is bdinfo-linux-x64. Do not select it on
        # non-Linux hosts, where it would fail with an exec-format error.
        system = platform.system().lower()
        machine = platform.machine().lower()
        if system == "linux" and machine in ("x86_64", "amd64"):
            candidates.append(base / "bin" / "bdinfo" / "bdinfo")

        for candidate in candidates:
            if candidate.is_file() and (system == "windows" or os.access(candidate, os.X_OK)):
                if debug:
                    console.print(f"[blue]Using bdinfo: {candidate}[/blue]")
                return str(candidate)

        path_binary = shutil.which("bdinfo")
        if path_binary:
            if debug:
                console.print(f"[blue]Using bdinfo from PATH: {path_binary}[/blue]")
            return path_binary

        raise FileNotFoundError(
            "bdinfo was not found. Install it and make `bdinfo` available "
            "on PATH, place it at <base_dir>/bin/bdinfo/bdinfo, or set BDINFO_PATH."
        )
