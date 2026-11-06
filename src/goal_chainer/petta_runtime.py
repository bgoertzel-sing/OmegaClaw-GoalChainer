"""Run MeTTa on the PeTTa runtime (MeTTa compiled to SWI-Prolog).

OmegaClaw and its deontic/NAL libraries run on PeTTa, not on the hyperon binary.
This wraps the PeTTa entrypoint so the rest of GoalChainer can hand it a MeTTa
program and get the result lines back.

How PeTTa is driven (from reading PeTTa/src):
- `swipl -q -s PeTTa/src/main.pl -- <file>.metta --silent`
- `--silent` suppresses the compile/run trace, so stdout carries only the result
  of each `!(...)` form, one per line (filereader.pl, main.pl).
- `(library X Y)` resolves under `<PeTTa>/X/Y` on older PeTTa; on PeTTa >= 3681b9b
  it needs a `library_path/1` entry ending in X, which `_library_path_goals` adds
  for the OmegaClaw-Core copy vendored inside PeTTa.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

DEFAULT_PETTA_DIR = Path("/home/user/Dev/PeTTa")
DEFAULT_PETTA_SWIPL = Path("/home/user/Dev/swipl-9.3.33/build-petta/src/swipl")


def petta_dir() -> Path:
    path = Path(os.environ.get("GOALCHAINER_PETTA_DIR", DEFAULT_PETTA_DIR))
    if not (path / "src" / "main.pl").exists():
        raise RuntimeError(f"PeTTa runtime not found at {path} (no src/main.pl)")
    return path


def petta_swipl() -> str:
    configured = os.environ.get("GOALCHAINER_PETTA_SWIPL")
    if configured:
        return configured
    if DEFAULT_PETTA_SWIPL.exists():
        return str(DEFAULT_PETTA_SWIPL)
    return "swipl"


def _library_dirs(root: Path) -> list[Path]:
    """Directories that `(library X Y)` should resolve against.

    PeTTa before compact-datatypes (e.g. 4ce1d0e) resolved `(library X Y)` as
    `<PeTTa>/lib/../X/Y`. From 3681b9b on it only consults `library_path/1`
    entries whose path ends in X, which `git-import!` registers. GoalChainer
    does not git-import OmegaClaw-Core, so register the vendored copies here.
    Override with GOALCHAINER_PETTA_LIBRARY_DIRS (os.pathsep separated).
    """

    configured = os.environ.get("GOALCHAINER_PETTA_LIBRARY_DIRS")
    if configured:
        return [Path(item) for item in configured.split(os.pathsep) if item]
    found: list[Path] = []
    for base in (root, root / "repos"):
        candidate = base / "OmegaClaw-Core"
        if candidate.is_dir():
            found.append(candidate)
    return found


def _library_path_goals(root: Path) -> list[str]:
    goals: list[str] = []
    for directory in _library_dirs(root):
        quoted = str(directory.absolute()).replace("\\", "\\\\").replace("'", "\\'")
        goals += ["-g", f"assertz(library_path('{quoted}'))"]
    return goals


def run_metta(program: str, work_dir: Path | None = None) -> list[str]:
    """Run a MeTTa program on PeTTa and return the non-empty stdout result lines.

    PeTTa sets its `working_dir` (used to resolve relative `import!`) to the program
    file's directory. Pass `work_dir` to place the file where a library's relative
    imports resolve, e.g. PeTTaChainer's `metta/` directory.
    """

    root = petta_dir()
    main_pl = root / "src" / "main.pl"
    with tempfile.NamedTemporaryFile(
        "w",
        delete=False,
        suffix=".metta",
        encoding="utf-8",
        dir=str(work_dir) if work_dir is not None else None,
    ) as handle:
        program_path = Path(handle.name)
        handle.write(program)
    try:
        result = subprocess.run(
            [
                petta_swipl(),
                "--stack_limit=8g",
                "-q",
                *_library_path_goals(root),
                "-s",
                str(main_pl),
                "--",
                str(program_path),
                "--silent",
            ],
            cwd=str(root),
            check=False,
            capture_output=True,
            text=True,
        )
    finally:
        program_path.unlink(missing_ok=True)

    if result.returncode != 0:
        raise RuntimeError(
            "PeTTa execution failed:\n"
            f"swipl={petta_swipl()} main={main_pl}\n"
            f"stdout={result.stdout}\n"
            f"stderr={result.stderr[-2000:]}"
        )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]
