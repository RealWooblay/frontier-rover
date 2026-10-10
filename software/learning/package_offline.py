#!/usr/bin/env python3
"""Copy committed project, private evidence and installed runtime outside the repo."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    destination = args.destination.expanduser().resolve()
    if destination == ROOT or ROOT in destination.parents:
        raise ValueError("Destination must be outside the original repo")
    if git("status", "--porcelain", "--untracked-files=normal").strip():
        raise ValueError("Commit and review public files before packaging")
    commit = git("rev-parse", "HEAD").decode().strip()
    remote = git("ls-remote", "origin", "refs/heads/main").decode().split()[0]
    if commit != remote:
        raise ValueError("GitHub main does not match this checkout")
    files = [Path(os.fsdecode(p)) for p in git("ls-files", "-z").split(b"\0") if p]
    destination.mkdir(parents=True, exist_ok=True)
    private = destination / "private"
    private.mkdir(exist_ok=True, mode=0o700)
    private.chmod(0o700)
    inventory = []

    def copy(relative: Path, target_root: Path, public: bool) -> None:
        source = ROOT / relative
        target = target_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if not public:
            target.chmod(0o600)
        expected = digest(source)
        if digest(target) != expected:
            raise IOError(f"Copy verification failed: {relative}")
        inventory.append({"source": relative.as_posix(),
                          "copy": str(target.relative_to(destination)),
                          "sha256": expected, "bytes": source.stat().st_size,
                          "public": public})

    for relative in files:
        copy(relative, destination / "project", True)
    ignored = [Path(os.fsdecode(p)) for p in git(
        "ls-files", "--others", "--ignored", "--exclude-standard", "-z"
    ).split(b"\0") if p]
    excluded = []
    for relative in ignored:
        if (relative.parts[0] in {".venv", "pi-images", ".artifact_work", "learning-output", ".pytest_cache"}
                or "__pycache__" in relative.parts or relative.name == ".DS_Store"
                or relative.suffix == ".pyc"):
            excluded.append(str(relative))
            continue
        copy(relative, private, False)

    runtime = destination / "runtime"
    runtime.mkdir(exist_ok=True)
    if not (runtime / ".venv").exists():
        # APFS copy-on-write cloning preserves files without an immediate full duplicate.
        subprocess.run(["/bin/cp", "-cR", str(ROOT / ".venv"), str(runtime / ".venv")], check=True)
    runtime_files = 0
    for source in (ROOT / ".venv").rglob("*"):
        target = runtime / ".venv" / source.relative_to(ROOT / ".venv")
        if source.is_symlink():
            if not target.is_symlink() or os.readlink(source) != os.readlink(target):
                raise IOError(f"Runtime symlink differs: {source}")
        elif source.is_file():
            if not target.is_file() or digest(source) != digest(target):
                raise IOError(f"Runtime file differs: {source}")
            runtime_files += 1
    for name in ("Open Workbook.command", "Run Simulation.command"):
        shutil.copy2(ROOT / "software/learning" / name, destination / name)
        (destination / name).chmod(0o755)
    shutil.copy2(ROOT / "docs/Frontier_Rover_Field_Guide.docx", destination / "Frontier_Rover_Field_Guide.docx")
    # A travel pack may have newer, reader-specific links outside the repo.
    if not (destination / "START HERE.md").exists():
        shutil.copy2(ROOT / "docs/backup-and-offline.md", destination / "START HERE.md")
    bundle = destination / "frontier-rover.bundle"
    subprocess.run(["git", "-C", str(ROOT), "bundle", "create", str(bundle), "--all"], check=True)
    subprocess.run(["git", "-C", str(ROOT), "bundle", "verify", str(bundle)], check=True)
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(), "source_commit": commit,
        "remote_main_commit": remote, "remote_verified": commit == remote,
        "source": str(ROOT), "files": inventory,
        "public_files": sum(row["public"] for row in inventory),
        "private_files": sum(not row["public"] for row in inventory),
        "runtime_files_verified": runtime_files,
        "runtime_python_target": str((runtime / ".venv/bin/python").resolve()),
        "bundle_sha256": digest(bundle), "excluded": excluded,
        "limitations": ["Not a Jetson SD-card image", "Private files are not on GitHub",
                        "Simulator requires existing bundled Python runtime on this Mac",
                        "Original checkout was not deleted"],
    }
    (destination / "backup-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({key: value for key, value in manifest.items()
                      if key not in {"files", "excluded"}}, indent=2))


if __name__ == "__main__":
    main()
