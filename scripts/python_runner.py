#!/usr/bin/env python3
"""Run a bundled Skill script with a compatible existing Python interpreter."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


SCRIPT_DIR = Path(__file__).resolve().parent
ALLOWED_SCRIPTS = {
    "annas_archive_client.py",
    "configure_key.py",
    "format_for_ima.py",
    "package_skill.py",
    "runtime_check.py",
}


def candidate_interpreters():
    values = []
    configured = os.environ.get("WORKBUDDY_PYTHON", "").strip()
    if configured:
        values.append(configured)
    values.append(sys.executable)
    for command in ("python3.13", "python3.12", "python3.11", "python3.10", "python3"):
        found = shutil.which(command)
        if found:
            values.append(found)

    home = Path.home()
    values.extend(
        str(path)
        for path in (
            Path("/opt/homebrew/bin/python3"),
            Path("/usr/local/bin/python3"),
            Path("/opt/miniconda3/envs/py312/bin/python"),
            Path("/opt/anaconda3/envs/py312/bin/python"),
            home / "miniconda3" / "envs" / "py312" / "bin" / "python",
            home / "anaconda3" / "envs" / "py312" / "bin" / "python",
        )
    )
    seen = set()
    for value in values:
        try:
            path = str(Path(value).expanduser().resolve())
        except OSError:
            continue
        if path not in seen and Path(path).is_file():
            seen.add(path)
            yield path


def compatible(path):
    probe = (
        "import ssl,sys; "
        "print(str(sys.version_info[0])+'.'+str(sys.version_info[1])+'|'+"
        "str(int(bool(getattr(ssl,'HAS_TLSv1_2',False)))))"
    )
    try:
        result = subprocess.run(
            [path, "-c", probe],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        version_text, tls_text = result.stdout.strip().split("|", 1)
        major, minor = (int(part) for part in version_text.split(".", 1))
        return result.returncode == 0 and (major, minor) >= (3, 10) and tls_text == "1"
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False


def emit_error(message):
    json.dump({"status": "needs_action", "error": message}, sys.stderr, ensure_ascii=False)
    sys.stderr.write("\n")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ALLOWED_SCRIPTS:
        emit_error("请指定一个允许执行的 Skill 脚本")
        return 2
    script = SCRIPT_DIR / sys.argv[1]
    if not script.is_file():
        emit_error("请求的 Skill 脚本不存在")
        return 2
    for interpreter in candidate_interpreters():
        if compatible(interpreter):
            os.execv(interpreter, [interpreter, str(script)] + sys.argv[2:])
    emit_error(
        "No existing Python 3.10+ interpreter with TLS 1.2 was found; install Python 3.12 or set WORKBUDDY_PYTHON"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
