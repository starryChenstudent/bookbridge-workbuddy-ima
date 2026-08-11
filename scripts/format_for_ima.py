#!/usr/bin/env python3
"""Validate or convert an Anna ebook into a format accepted by IMA."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile


MB = 1024 * 1024
DIRECT_TYPES = {
    "pdf": {"media_type": 1, "content_type": "application/pdf", "limit": 200 * MB},
    "epub": {"media_type": 21, "content_type": "application/epub+zip", "limit": 50 * MB},
    "doc": {"media_type": 3, "content_type": "application/msword", "limit": 200 * MB},
    "docx": {
        "media_type": 3,
        "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "limit": 200 * MB,
    },
    "txt": {"media_type": 13, "content_type": "text/plain", "limit": 10 * MB},
    "md": {"media_type": 7, "content_type": "text/markdown", "limit": 10 * MB},
    "markdown": {"media_type": 7, "content_type": "text/markdown", "limit": 10 * MB},
    "html": {"media_type": 20, "content_type": "text/html", "limit": 10 * MB},
}
DIRECT_LIMITS = {extension: metadata["limit"] for extension, metadata in DIRECT_TYPES.items()}
CONVERTIBLE_TO_EPUB = frozenset({"mobi", "azw", "azw3", "fb2", "rtf", "djvu"})
DEFAULT_KB_NAME_PATH = (
    Path.home() / ".config" / "local-reading-assistant" / "default_ima_knowledge_base_name"
)


class FormatError(RuntimeError):
    pass


def emit(payload: dict, *, stream=sys.stdout) -> None:
    json.dump(payload, stream, ensure_ascii=False, indent=2)
    stream.write("\n")


def validate_epub(path: Path) -> None:
    if not zipfile.is_zipfile(path):
        raise FormatError("Converted output is not a valid EPUB ZIP container")
    with zipfile.ZipFile(path) as archive:
        if "META-INF/container.xml" not in archive.namelist():
            raise FormatError("Converted EPUB is missing META-INF/container.xml")


def direct_upload_metadata(path: Path, source_format: str) -> dict:
    metadata = DIRECT_TYPES[source_format]
    stat = path.stat()
    return {
        "file_path": str(path),
        "file_name": path.name,
        "file_ext": source_format,
        "file_size": stat.st_size,
        "last_modify_time": int(stat.st_mtime),
        "media_type": metadata["media_type"],
        "content_type": metadata["content_type"],
        "max_bytes": metadata["limit"],
    }


def inspect_source(source: Path) -> dict:
    source = source.expanduser().resolve()
    if not source.is_file():
        raise FormatError(f"Source file does not exist: {source}")
    source_format = source.suffix.lstrip(".").lower()
    size = source.stat().st_size
    if source_format in DIRECT_TYPES:
        limit = DIRECT_TYPES[source_format]["limit"]
        if size > limit:
            raise FormatError(
                f"{source_format.upper()} is {size / MB:.1f} MB and exceeds IMA's {limit / MB:.0f} MB limit"
            )
        if source_format == "pdf":
            with source.open("rb") as handle:
                if not handle.read(8).startswith(b"%PDF-"):
                    raise FormatError("PDF signature is invalid")
        if source_format == "epub":
            validate_epub(source)
        return {
            "status": "direct",
            "source_file": str(source),
            "source_format": source_format,
            "ima_file": str(source),
            "ima_format": source_format,
            "conversion_required": False,
            "bytes": size,
            **direct_upload_metadata(source, source_format),
        }
    if source_format in CONVERTIBLE_TO_EPUB:
        return {
            "status": "convertible",
            "source_file": str(source),
            "source_format": source_format,
            "ima_file": "",
            "ima_format": "epub",
            "conversion_required": True,
            "bytes": size,
            "ebook_convert": shutil.which("ebook-convert") or "unavailable",
        }
    raise FormatError(
        "Format is not supported by this book workflow; choose PDF/EPUB/DOCX/TXT or a Calibre-convertible edition"
    )


def convert_source(source: Path) -> dict:
    inspected = inspect_source(source)
    if not inspected["conversion_required"]:
        return inspected
    executable = shutil.which("ebook-convert")
    if not executable:
        raise FormatError(
            f"{inspected['source_format'].upper()} cannot be uploaded to IMA directly; install Calibre or choose a PDF/EPUB edition"
        )
    source_path = Path(inspected["source_file"])
    output_path = source_path.with_name(f"{source_path.stem}.ima.epub")
    if output_path.is_file():
        validate_epub(output_path)
        if output_path.stat().st_size > DIRECT_LIMITS["epub"]:
            raise FormatError("Existing converted EPUB exceeds IMA's 50 MB limit")
        return {
            **inspected,
            "status": "existing_converted",
            "ima_file": str(output_path.resolve()),
            "bytes": output_path.stat().st_size,
            **direct_upload_metadata(output_path.resolve(), "epub"),
        }
    with tempfile.TemporaryDirectory(prefix="ima-ebook-convert-") as directory:
        part_path = Path(directory) / "converted.epub"
        try:
            result = subprocess.run(
                [executable, str(source_path), str(part_path)],
                capture_output=True,
                text=True,
                timeout=900,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise FormatError("ebook-convert timed out after 15 minutes") from exc
        except OSError as exc:
            raise FormatError(f"Could not run ebook-convert: {exc}") from exc
        if result.returncode != 0:
            detail = re.sub(r"\s+", " ", result.stderr or result.stdout).strip()[-500:]
            raise FormatError(f"ebook-convert failed: {detail or 'unknown error'}")
        validate_epub(part_path)
        if part_path.stat().st_size > DIRECT_LIMITS["epub"]:
            raise FormatError("Converted EPUB exceeds IMA's 50 MB limit")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_output = output_path.with_name(f".{output_path.name}.part")
        shutil.copyfile(part_path, temp_output)
        os.replace(temp_output, output_path)
    return {
        **inspected,
        "status": "converted",
        "ima_file": str(output_path.resolve()),
        "bytes": output_path.stat().st_size,
        "original_retained": True,
        **direct_upload_metadata(output_path.resolve(), "epub"),
    }


def get_default_knowledge_base_name(path: Path = DEFAULT_KB_NAME_PATH) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return ""


def set_default_knowledge_base_name(name: str, path: Path = DEFAULT_KB_NAME_PATH) -> None:
    name = name.strip()
    if not name:
        raise FormatError("Knowledge base name cannot be empty")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False, prefix=".ima-target-"
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            handle.write(name + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            temp_path.chmod(0o600)
        except OSError:
            pass
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("inspect", "prepare"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--file", required=True)
    subparsers.add_parser("target-get")
    target_set = subparsers.add_parser("target-set")
    target_set.add_argument("--name", required=True)
    args = parser.parse_args()
    try:
        if args.command == "inspect":
            result = inspect_source(Path(args.file))
        elif args.command == "prepare":
            result = convert_source(Path(args.file))
        elif args.command == "target-get":
            name = get_default_knowledge_base_name()
            emit({"status": "ok" if name else "missing", "knowledge_base_name": name})
            return 0 if name else 2
        else:
            set_default_knowledge_base_name(args.name)
            result = {"status": "configured", "knowledge_base_name": args.name.strip(), "id_stored": False}
        emit(result)
        return 0
    except FormatError as exc:
        emit({"status": "error", "error": str(exc)}, stream=sys.stderr)
        return 2
    except KeyboardInterrupt:
        emit({"status": "error", "error": "Operation cancelled"}, stream=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
