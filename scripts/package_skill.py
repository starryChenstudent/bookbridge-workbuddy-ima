#!/usr/bin/env python3
"""Create a credential-free master ZIP or a private preconfigured ZIP."""

from __future__ import annotations

import argparse
import getpass
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = SKILL_ROOT.parents[2] / "BookBridge-WorkBuddy.zip"
KEYCHAIN_SERVICE = "workbuddy-annas-archive"
ENV_NAME = "ANNAS_ARCHIVE_API_KEY"
PACKAGE_ROOT_NAME = "bookbridge"
SKILL_ENTRIES = {"SKILL.md", "agents", "references", "scripts"}


def should_include(relative: Path) -> bool:
    if not relative.parts or relative.parts[0] not in SKILL_ENTRIES:
        return False
    if any(part in {".git", ".github"} for part in relative.parts):
        return False
    if relative.name == ".DS_Store":
        return False
    if relative.name == ".env" or relative.name == "api_key":
        return False
    if relative.suffix.lower() in {".key", ".pem"}:
        return False
    if "__pycache__" in relative.parts or relative.suffix == ".pyc":
        return False
    if relative.parts and relative.parts[0] == "library":
        return False
    if relative.parts and relative.parts[0] == "config":
        return False
    if relative.name == "library-index.sqlite3" or ".work" in relative.parts:
        return False
    if relative.name.startswith("test_"):
        return False
    if relative.as_posix() in {
        "references/note-schema.md",
        "references/ima-knowledge-base-api.md",
        "scripts/book_library.py",
        "scripts/configure_credentials.py",
        "scripts/configure_ima.py",
        "scripts/epub_to_pdf.py",
        "scripts/ima_api.cjs",
        "scripts/ima_kb_client.cjs",
        "scripts/pdf_extract.js",
        "scripts/prepare_delivery.py",
    }:
        return False
    return True


def normalize_secret(secret: str) -> str:
    secret = secret.strip()
    if not secret:
        raise ValueError("Anna API Key 不能为空")
    if any(character in secret for character in ("\x00", "\r", "\n")):
        raise ValueError("Anna API Key 包含不允许的控制字符")
    return secret


def private_env_payload(secret: str) -> bytes:
    return f"{ENV_NAME}={normalize_secret(secret)}\n".encode("utf-8")


def key_from_keychain(account: str) -> str:
    if sys.platform != "darwin" or shutil.which("security") is None:
        raise RuntimeError("当前系统无法读取 macOS 钥匙串")
    result = subprocess.run(
        ["security", "find-generic-password", "-a", account, "-s", KEYCHAIN_SERVICE, "-w"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("未找到 Anna API Key 钥匙串项目")
    return normalize_secret(result.stdout)


def prompt_private_secret() -> str:
    first = getpass.getpass("请输入写入私版的 Anna API Key（隐藏输入）：")
    second = getpass.getpass("请再次输入 Anna API Key（隐藏输入）：")
    if first != second:
        raise ValueError("两次输入的 Anna API Key 不一致")
    return normalize_secret(first)


def package_files() -> list[Path]:
    return [
        path
        for path in sorted(SKILL_ROOT.rglob("*"))
        if path.is_file() and should_include(path.relative_to(SKILL_ROOT))
    ]


def build_package(output: Path, private_secret: str | None = None) -> dict[str, object]:
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    files = package_files()
    packaged_env = private_env_payload(private_secret) if private_secret is not None else None
    root_name = PACKAGE_ROOT_NAME
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, Path(root_name) / path.relative_to(SKILL_ROOT))
        if packaged_env is not None:
            info = zipfile.ZipInfo(str(Path(root_name) / "config" / ".env"))
            info.external_attr = 0o600 << 16
            archive.writestr(info, packaged_env, compress_type=zipfile.ZIP_DEFLATED)
    verified = False
    if packaged_env is not None:
        with zipfile.ZipFile(output) as archive:
            verified = archive.read(str(Path(root_name) / "config" / ".env")) == packaged_env
        if not verified:
            raise RuntimeError("私版凭证写入验证失败")
    return {
        "output": output,
        "files": len(files) + (1 if packaged_env is not None else 0),
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "private": packaged_env is not None,
        "private_credential_verified": verified,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    private_group = parser.add_mutually_exclusive_group()
    private_group.add_argument("--private", action="store_true", help="通过中文隐藏输入生成私版")
    private_group.add_argument(
        "--private-from-keychain",
        action="store_true",
        help="从当前 Mac 钥匙串读取并生成私版，不显示 Key",
    )
    parser.add_argument("--account", default=getpass.getuser(), help="macOS 钥匙串账户名称")
    args = parser.parse_args()
    try:
        secret = None
        if args.private:
            secret = prompt_private_secret()
        elif args.private_from_keychain:
            secret = key_from_keychain(args.account)
        result = build_package(Path(args.output), secret)
    except (ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    print(f"package={result['output']}")
    print(f"package_type={'private' if result['private'] else 'master'}")
    print(f"files={result['files']}")
    print(f"sha256={result['sha256']}")
    print(f"anna_credentials_included={'yes' if result['private'] else 'no'}")
    print("ima_credentials_included=no")
    print("ima_transport=workbuddy-mcp-plus-streaming-cos")
    print("library_data_included=no")
    if result["private"]:
        print(f"private_credential_verified={'yes' if result['private_credential_verified'] else 'no'}")
        print("warning=private edition contains a plaintext Anna API Key; do not redistribute")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
