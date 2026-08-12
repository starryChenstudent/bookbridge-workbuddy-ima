#!/usr/bin/env python3
"""Resolve the visible desktop library and migrate legacy Skill-local data safely."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parent.parent
LEGACY_LIBRARY_ROOT = SKILL_ROOT / "library"


def resolve_desktop_dir() -> Path:
    configured = os.environ.get("WORKBUDDY_DESKTOP_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()

    home = Path.home()
    if os.name == "nt":
        candidates = [home / "Desktop"]
        for variable in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
            value = os.environ.get(variable, "").strip()
            if value:
                candidates.append(Path(value) / "Desktop")
        for candidate in candidates:
            if candidate.is_dir():
                return candidate.resolve()

    xdg_config = home / ".config" / "user-dirs.dirs"
    try:
        content = xdg_config.read_text(encoding="utf-8")
        match = re.search(r'^XDG_DESKTOP_DIR="([^"]+)"', content, re.MULTILINE)
        if match:
            value = match.group(1).replace("$HOME", str(home))
            return Path(value).expanduser().resolve()
    except OSError:
        pass
    return (home / "Desktop").resolve()


def resolve_library_root() -> Path:
    configured = os.environ.get("WORKBUDDY_LIBRARY_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return resolve_desktop_dir() / "library"


LIBRARY_ROOT = resolve_library_root()
BOOKS_DIR = LIBRARY_ROOT / "books"
NOTES_DIR = LIBRARY_ROOT / "notes"
WORK_DIR = NOTES_DIR / ".work"
INDEX_PATH = NOTES_DIR / "library-index.sqlite3"


def migrate_legacy_library(
    legacy_root: Path = LEGACY_LIBRARY_ROOT,
    library_root: Path = LIBRARY_ROOT,
) -> dict[str, Any]:
    copied = 0
    skipped_existing = 0
    skipped_unsafe = 0
    errors: list[str] = []
    try:
        same_location = legacy_root.resolve() == library_root.resolve()
    except OSError:
        same_location = False
    if same_location or not legacy_root.is_dir():
        return {
            "legacy_found": legacy_root.is_dir(),
            "copied": copied,
            "skipped_existing": skipped_existing,
            "skipped_unsafe": skipped_unsafe,
            "errors": errors,
        }

    for section in ("books", "notes"):
        source_root = legacy_root / section
        if not source_root.is_dir():
            continue
        for source in sorted(source_root.rglob("*")):
            if not source.is_file() or source.is_symlink():
                if source.is_symlink():
                    skipped_unsafe += 1
                continue
            relative = source.relative_to(source_root)
            if source.name in {".DS_Store", ".gitkeep"}:
                continue
            target = library_root / section / relative
            if target.exists():
                skipped_existing += 1
                continue
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                copied += 1
            except OSError as exc:
                errors.append(f"{section}/{relative}: {type(exc).__name__}")
    return {
        "legacy_found": True,
        "copied": copied,
        "skipped_existing": skipped_existing,
        "skipped_unsafe": skipped_unsafe,
        "errors": errors[:20],
    }


def ensure_library(*, migrate_legacy: bool = True) -> dict[str, Any]:
    BOOKS_DIR.mkdir(parents=True, exist_ok=True)
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    migration = migrate_legacy_library() if migrate_legacy else {
        "legacy_found": LEGACY_LIBRARY_ROOT.is_dir(),
        "copied": 0,
        "skipped_existing": 0,
        "skipped_unsafe": 0,
        "errors": [],
    }
    return {
        "library_root": str(LIBRARY_ROOT),
        "books_dir": str(BOOKS_DIR),
        "notes_dir": str(NOTES_DIR),
        "migration": migration,
    }
