#!/usr/bin/env python3
"""在 Skill 外安全保存或检查 Anna 会员 API Key。"""

from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


CONFIG_DIR = Path.home() / ".config" / "annas-archive"
API_KEY_PATH = CONFIG_DIR / "api_key"
ENV_NAME = "ANNAS_ARCHIVE_API_KEY"
KEYCHAIN_SERVICE = "workbuddy-annas-archive"
SKILL_ROOT = Path(__file__).resolve().parent.parent
PACKAGED_ENV_PATH = SKILL_ROOT / "config" / ".env"


def file_has_key(path: Path | None = None) -> bool:
    path = API_KEY_PATH if path is None else path
    try:
        return bool(path.read_text(encoding="utf-8").strip())
    except (OSError, UnicodeError):
        return False


def ensure_config_dir(path: Path = CONFIG_DIR) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.chmod(0o700)
    except OSError:
        pass


def packaged_key_present(path: Path | None = None) -> bool:
    path = PACKAGED_ENV_PATH if path is None else path
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            name, separator, value = line.partition("=")
            if separator and name.strip() == ENV_NAME:
                return bool(value.strip())
    except (OSError, UnicodeError):
        pass
    return False


def configured() -> dict[str, object]:
    env_configured = bool(os.environ.get(ENV_NAME, "").strip())
    file_configured = file_has_key()
    packaged_configured = packaged_key_present()
    if env_configured:
        source = "environment"
        location = "environment"
    elif file_configured:
        source = "user_config"
        location = str(CONFIG_DIR)
    elif packaged_configured:
        source = "private_package"
        location = str(PACKAGED_ENV_PATH.parent)
    else:
        source = "missing"
        location = str(CONFIG_DIR)
    return {
        "configured": env_configured or file_configured or packaged_configured,
        "source": source,
        "location": location,
    }


def atomic_secret(secret: str, path: Path = API_KEY_PATH) -> None:
    secret = secret.strip()
    if not secret:
        raise ValueError("API key cannot be empty")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
        prefix=".anna-secret-",
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            handle.write(secret + "\n")
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


def emit(payload: dict[str, object], *, stream=sys.stdout) -> None:
    json.dump(payload, stream, ensure_ascii=False, indent=2)
    stream.write("\n")


def check_key() -> int:
    state = configured()
    emit(
        {
            "status": "ok" if state["configured"] else "needs_action",
            **state,
            "credential_printed": False,
            "credential_bundled": False,
        }
    )
    return 0 if state["configured"] else 2


def prompt_key() -> int:
    ensure_config_dir()
    print(f"将把 Anna API Key 安全保存在：{API_KEY_PATH}")
    print("输入内容会被隐藏，不会写入聊天记录或 Skill 压缩包。")
    first = getpass.getpass("请输入 Anna API Key（隐藏输入）：")
    second = getpass.getpass("请再次输入 Anna API Key（隐藏输入）：")
    if first != second:
        emit({"status": "error", "error": "两次输入的 Anna API Key 不一致"}, stream=sys.stderr)
        return 2
    try:
        atomic_secret(first)
    except ValueError as exc:
        emit({"status": "error", "error": "Anna API Key 不能为空"}, stream=sys.stderr)
        return 2
    emit(
        {
            "status": "configured",
            "message": "Anna API Key 已安全保存，后续不会重复询问",
            "location": str(CONFIG_DIR),
            "credential_printed": False,
            "credential_bundled": False,
        }
    )
    return 0


def import_keychain(account: str) -> int:
    if sys.platform != "darwin" or shutil.which("security") is None:
        emit({"status": "error", "error": "当前系统无法使用 macOS 钥匙串"}, stream=sys.stderr)
        return 2
    result = subprocess.run(
        ["security", "find-generic-password", "-a", account, "-s", KEYCHAIN_SERVICE, "-w"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        emit({"status": "needs_action", "error": "未找到对应的 macOS 钥匙串项目"}, stream=sys.stderr)
        return 1
    atomic_secret(result.stdout)
    emit(
        {
            "status": "configured",
            "message": "Anna API Key 已从 macOS 钥匙串导入",
            "source": "macos_keychain",
            "location": str(CONFIG_DIR),
            "credential_printed": False,
            "credential_bundled": False,
        }
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--import-keychain", action="store_true")
    parser.add_argument(
        "--account",
        default=getpass.getuser(),
        help="用于 --import-keychain 的 macOS 钥匙串账户名称",
    )
    args = parser.parse_args()
    if args.check and args.import_keychain:
        parser.error("--check 与 --import-keychain 只能选择一个")
    if args.check:
        return check_key()
    if args.import_keychain:
        return import_keychain(args.account)
    return prompt_key()


if __name__ == "__main__":
    raise SystemExit(main())
