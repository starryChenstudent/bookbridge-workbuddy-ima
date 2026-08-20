#!/usr/bin/env python3
"""Check the local Anna download and MCP-assisted IMA upload runtime."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import library_paths
import configure_key
import format_for_ima


SKILL_ROOT = Path(__file__).resolve().parent.parent
ANNA_CONFIG_DIR = Path.home() / ".config" / "annas-archive"
ANNA_API_KEY_FILE = ANNA_CONFIG_DIR / "api_key"
BOOKBRIDGE_RECORD_CACHE = Path(
    os.environ.get(
        "BOOKBRIDGE_RECORD_CACHE",
        str(Path.home() / ".config" / "bookbridge" / "records.json"),
    )
).expanduser()


def node_runtime():
    executable = shutil.which("node")
    if not executable:
        return "", "", False
    try:
        result = subprocess.run(
            [executable, "--version"], capture_output=True, text=True, timeout=8, check=False
        )
        version = result.stdout.strip().lstrip("v")
        major = int(version.split(".", 1)[0])
        return executable, version, result.returncode == 0 and major >= 18
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return executable, "unknown", False


def nonempty_file(path):
    try:
        return bool(path.read_text(encoding="utf-8").strip())
    except (OSError, UnicodeError):
        return False


def directory_writable(path):
    try:
        path.mkdir(parents=True, exist_ok=True)
        return os.access(path, os.W_OK)
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    actions = []
    if sys.version_info < (3, 10):
        actions.append("Install or select Python 3.10 or newer")

    node, node_version, node_supported = node_runtime()
    if not node_supported:
        actions.append("Install or select Node.js 18 or newer for IMA uploads")
    ebook_convert = shutil.which("ebook-convert")

    anna_state = configure_key.configured()
    anna_credential_configured = bool(anna_state["configured"])

    if not anna_credential_configured:
        actions.append("Run configure_key.py for guided Chinese Anna credential setup")

    ima_default_name = format_for_ima.get_default_knowledge_base_name()
    ima_default_configured = bool(ima_default_name)

    cached_record_count = 0
    if BOOKBRIDGE_RECORD_CACHE.exists():
        try:
            cache_payload = json.loads(BOOKBRIDGE_RECORD_CACHE.read_text(encoding="utf-8"))
            cached_record_count = len(cache_payload.get("records", []))
        except (OSError, UnicodeError, json.JSONDecodeError, AttributeError, TypeError):
            actions.append("Repair or remove the invalid local BookBridge record cache")

    migration = {"legacy_found": False, "copied": 0, "skipped_existing": 0, "errors": []}
    try:
        library = library_paths.ensure_library(migrate_legacy=True)
        migration = library["migration"]
    except OSError as exc:
        library = {
            "library_root": str(library_paths.LIBRARY_ROOT),
            "books_dir": str(library_paths.BOOKS_DIR),
            "notes_dir": str(library_paths.NOTES_DIR),
        }
        actions.append(f"Create the desktop library manually: {type(exc).__name__}")
    books_writable = directory_writable(library_paths.BOOKS_DIR)
    if not books_writable:
        actions.append("Grant write access to the desktop library/books directory")
    if migration.get("errors"):
        actions.append("Some legacy library files could not be copied to the desktop")

    payload = {
        "status": "ok" if not actions else "needs_action",
        "python": sys.version.split()[0],
        "python_supported": sys.version_info >= (3, 10),
        "third_party_python_packages": [],
        "pip_install_required": False,
        "node": node or "unavailable",
        "node_version": node_version or "unavailable",
        "node_supported": node_supported,
        "agent_browser_required": False,
        "record_discovery_mode": "user-supplied-record-or-local-cache",
        "direct_record_inputs": ["official /md5/ URL", "32-character MD5"],
        "record_cache_location": str(BOOKBRIDGE_RECORD_CACHE),
        "cached_record_count": cached_record_count,
        "ebook_convert": ebook_convert or "optional-unavailable",
        "anna_credential_configured": anna_credential_configured,
        "anna_credential_source": anna_state["source"],
        "anna_credential_location": anna_state["location"],
        "anna_private_package_supported": True,
        "ima_local_credentials_required": False,
        "ima_connector_required": "ima-mcp",
        "ima_connector_check": "performed by the WorkBuddy agent at runtime",
        "ima_default_knowledge_base_configured": ima_default_configured,
        "ima_default_knowledge_base_name": ima_default_name,
        "ima_api_transport": "workbuddy-mcp",
        "ima_binary_upload_transport": "local-stream-to-cos",
        "format_priority": ["pdf", "epub", "docx", "txt", "convertible-to-epub"],
        "ima_direct_book_formats": ["pdf", "epub", "doc", "docx", "txt", "md", "html"],
        "calibre_convertible_book_formats": ["mobi", "azw", "azw3", "fb2", "rtf", "djvu"],
        "library_writable": books_writable,
        "library_root": library["library_root"],
        "books_dir": library["books_dir"],
        "notes_dir": library["notes_dir"],
        "legacy_migration": migration,
        "automatic_system_install": False,
        "actions": actions,
    }
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if not actions else 2


if __name__ == "__main__":
    raise SystemExit(main())
