#!/usr/bin/env python3
"""Search Anna's Archive and download authorized ebooks without a proxy.

The member key is read from the per-user environment or config directory. It is
never bundled with the Skill, accepted as a command-line argument, or printed.
Temporary download URLs are never printed.
"""

from __future__ import annotations

import argparse
import codecs
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, BinaryIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
import zipfile

import library_paths


DEFAULT_BASE_URL = "https://tw.annas-archive.gl"
ALLOWED_OFFICIAL_HOSTS = frozenset({"annas-archive.gl", "tw.annas-archive.gl"})
SKILL_ROOT = Path(__file__).resolve().parent.parent
USER_API_KEY_FILE = Path.home() / ".config" / "annas-archive" / "api_key"
API_KEY_ENV = "ANNAS_ARCHIVE_API_KEY"
PACKAGED_ENV_FILE = SKILL_ROOT / "config" / ".env"
DEFAULT_BOOKS_DIR = library_paths.BOOKS_DIR
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
MAX_API_RESPONSE_BYTES = 1_048_576
DEFAULT_MAX_SEARCH_BYTES = 8 * 1024 * 1024
SEARCH_READ_CHUNK_BYTES = 64 * 1024
MAX_SEARCH_BLOCK_CHARS = 2 * 1024 * 1024
DEFAULT_MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024
ALLOWED_FORMATS = frozenset(
    {"epub", "pdf", "mobi", "azw", "azw3", "docx", "txt", "fb2", "rtf", "djvu"}
)
RIGHTS_BASES = ("public-domain", "open-license", "user-authorization")
CONTENT_TYPES = ("book_any", "book_fiction", "book_nonfiction", "journal")
SEARCH_RESULT_START = re.compile(
    r'<div\s+class="flex\s+pt-3\s+pb-3\s+border-b\s+last:border-b-0\s+border-gray-100">'
)
SEARCH_RESULT_MARKER = (
    '<div class="flex  pt-3 pb-3 border-b last:border-b-0 border-gray-100">'
)


class ClientError(RuntimeError):
    """A user-actionable error with secret-safe text."""


class RestrictedRedirectHandler(HTTPRedirectHandler):
    """Allow only HTTPS redirects and optionally restrict destination hosts."""

    def __init__(self, allowed_hosts: frozenset[str] | None, max_redirects: int = 5):
        super().__init__()
        self.allowed_hosts = allowed_hosts
        self.max_redirects = max_redirects
        self.redirects = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        self.redirects += 1
        if self.redirects > self.max_redirects:
            raise ClientError("Too many HTTP redirects")
        parsed = urlsplit(newurl)
        if parsed.scheme.lower() != "https":
            raise ClientError("Refusing a non-HTTPS redirect")
        if self.allowed_hosts is not None and parsed.hostname not in self.allowed_hosts:
            raise ClientError("Refusing a redirect outside the official Anna's Archive hosts")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def emit_json(payload: dict[str, Any], *, stream=sys.stdout) -> None:
    json.dump(payload, stream, ensure_ascii=False, indent=2)
    stream.write("\n")


def emit_progress(payload: dict[str, Any]) -> None:
    sys.stderr.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stderr.flush()


def hash_file(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def redact(text: str, secret: str | None = None) -> str:
    safe = text
    if secret:
        safe = safe.replace(secret, "[REDACTED]")
    safe = re.sub(r"([?&]key=)[^&\s]+", r"\1[REDACTED]", safe, flags=re.I)
    safe = re.sub(r"https://[^\s\"']+", "[REDACTED_URL]", safe)
    return safe[:1000]


def normalize_official_base_url(raw: str) -> str:
    parsed = urlsplit(raw.strip().rstrip("/"))
    if parsed.scheme.lower() != "https" or parsed.hostname not in ALLOWED_OFFICIAL_HOSTS:
        raise ClientError(
            "Base URL must be HTTPS and use annas-archive.gl or tw.annas-archive.gl"
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ClientError("Base URL must not include credentials, query parameters, or fragments")
    if parsed.path not in ("", "/"):
        raise ClientError("Base URL must not include a path")
    return f"https://{parsed.hostname}"


def read_packaged_env_key(path: Path | None = None) -> str:
    path = PACKAGED_ENV_FILE if path is None else path
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except (OSError, UnicodeDecodeError):
        raise ClientError("The packaged Anna credential file is unreadable") from None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        if separator and name.strip() == API_KEY_ENV:
            secret = value.strip()
            if "\x00" in secret or "\r" in secret or "\n" in secret:
                raise ClientError("The packaged Anna credential is invalid")
            return secret
    return ""


def load_secret_key() -> str:
    environment_secret = os.environ.get(API_KEY_ENV, "").strip()
    if environment_secret:
        return environment_secret
    try:
        secret = USER_API_KEY_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        secret = read_packaged_env_key()
        if secret:
            return secret
        raise ClientError(
            "Anna API key is not configured; use a preconfigured private package or run scripts/configure_key.py"
        ) from None
    except (OSError, UnicodeDecodeError):
        raise ClientError("The per-user Anna API key file is unreadable") from None
    if not secret:
        secret = read_packaged_env_key()
    if not secret:
        raise ClientError(
            "Anna API key is not configured; use a preconfigured private package or run scripts/configure_key.py"
        )
    return secret


def safe_http_error(error: HTTPError, secret: str | None = None) -> ClientError:
    try:
        body = error.read(2048).decode("utf-8", errors="replace")
        parsed = json.loads(body)
        detail = str(parsed.get("error") or "") if isinstance(parsed, dict) else ""
    except Exception:
        detail = ""
    message = f"HTTP request failed with status {error.code}"
    if detail:
        message += f": {detail}"
    return ClientError(redact(message, secret))


def open_request(
    request: Request,
    *,
    timeout: float,
    allowed_redirect_hosts: frozenset[str] | None,
    secret: str | None = None,
):
    # Explicitly disable environment and system proxy discovery. This is a
    # portability and privacy requirement of the Skill.
    opener = build_opener(
        ProxyHandler({}), RestrictedRedirectHandler(allowed_redirect_hosts)
    )
    try:
        return opener.open(request, timeout=timeout)
    except HTTPError as exc:
        raise safe_http_error(exc, secret) from None
    except URLError as exc:
        reason = redact(str(exc.reason), secret)
        raise ClientError(f"Network request failed: {reason}") from None


def strip_markup(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def extract_link_text(block: str, icon_name: str) -> str:
    pattern = re.compile(
        rf'<a\s+href="/search\?q=[^"]*"[^>]*>'
        rf'.*?<span\s+class="[^"]*{re.escape(icon_name)}[^"]*"[^>]*></span>'
        rf'(.*?)</a>',
        re.S,
    )
    match = pattern.search(block)
    return strip_markup(match.group(1)) if match else ""


def parse_search_results(
    html_text: str,
    *,
    base_url: str,
    language: str | None = None,
    file_format: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    blocks = SEARCH_RESULT_START.split(html_text)[1:]
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    for block in blocks:
        cover = re.search(
            r'<a\s+href="/md5/([0-9a-fA-F]{32})"\s+class="custom-a block [^"]+">',
            block,
        )
        if not cover:
            continue
        md5 = cover.group(1).lower()
        if md5 in seen:
            continue

        title_match = re.search(
            rf'<a\s+href="/md5/{md5}"\s+class="[^"]*js-vim-focus[^"]*"[^>]*>(.*?)</a>',
            block,
            re.S | re.I,
        )
        if not title_match:
            continue
        title = strip_markup(title_match.group(1))
        authors = extract_link_text(block, "icon-[mdi--user-edit]")
        publisher = extract_link_text(block, "icon-[mdi--company]")

        metadata_match = re.search(
            r'<div\s+class="text-gray-800[^"]*"[^>]*>([^<]*)', block, re.S
        )
        metadata = strip_markup(metadata_match.group(1)) if metadata_match else ""
        lang_match = re.search(r"([^·]+?)\s*\[([a-zA-Z-]+)\]", metadata)
        format_match = re.search(
            r"\b(EPUB|PDF|MOBI|AZW3|AZW|DJVU|CBZ|CBR|FB2|DOCX?|TXT|RTF|ZIP)\b",
            metadata,
            re.I,
        )
        size_match = re.search(r"\b\d+(?:\.\d+)?\s*(?:KB|MB|GB|TB)\b", metadata, re.I)
        year_match = re.search(r"(?:^|·)\s*((?:18|19|20)\d{2})\s*(?:·|$)", metadata)

        language_name = lang_match.group(1).strip(" ✅") if lang_match else ""
        language_code = lang_match.group(2).lower() if lang_match else ""
        detected_format = format_match.group(1).lower() if format_match else ""
        if language and language.lower() not in {language_name.lower(), language_code}:
            continue
        if file_format and file_format.lower() != detected_format:
            continue

        results.append(
            {
                "title": title,
                "authors": authors,
                "publisher": publisher,
                "year": year_match.group(1) if year_match else "",
                "language": language_name,
                "language_code": language_code,
                "format": detected_format,
                "size": size_match.group(0).replace(" ", "") if size_match else "",
                "md5": md5,
                "record_url": urljoin(base_url, f"/md5/{md5}"),
            }
        )
        seen.add(md5)
        if len(results) >= limit:
            break

    return results


def parse_streamed_search_response(
    response,
    *,
    base_url: str,
    language: str | None,
    file_format: str | None,
    limit: int,
    max_bytes: int,
    deadline: float | None = None,
) -> list[dict[str, Any]]:
    """Parse result blocks incrementally without retaining the full HTML page."""
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    buffer = ""
    started = False
    eof = False
    bytes_read = 0
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    def consume(block: str) -> None:
        if not block or len(results) >= limit:
            return
        parsed = parse_search_results(
            SEARCH_RESULT_MARKER + block,
            base_url=base_url,
            language=language,
            file_format=file_format,
            limit=1,
        )
        if parsed and parsed[0]["md5"] not in seen:
            seen.add(parsed[0]["md5"])
            results.append(parsed[0])

    while len(results) < limit:
        if deadline is not None and time.monotonic() >= deadline:
            raise ClientError("Search exceeded the configured overall safety deadline")
        try:
            raw = response.read(SEARCH_READ_CHUNK_BYTES)
        except (OSError, TimeoutError):
            raise ClientError("Search response read timed out or was interrupted") from None
        if raw:
            bytes_read += len(raw)
            if bytes_read > max_bytes:
                raise ClientError(
                    "Search response exceeded the low-memory safety limit; refine the query"
                )
            buffer += decoder.decode(raw)
        else:
            buffer += decoder.decode(b"", final=True)
            eof = True

        while True:
            marker = SEARCH_RESULT_START.search(buffer)
            if not started:
                if marker is None:
                    # The result list is near the beginning of the page. Keep
                    # only enough tail to recognize a marker split across reads.
                    if len(buffer) > 4096:
                        buffer = buffer[-4096:]
                    break
                started = True
                buffer = buffer[marker.end() :]
                continue
            if marker is None:
                if len(buffer) > MAX_SEARCH_BLOCK_CHARS:
                    raise ClientError("A search result block exceeded the memory safety limit")
                break
            consume(buffer[: marker.start()])
            buffer = buffer[marker.end() :]
            if len(results) >= limit:
                break

        if eof:
            if started and len(results) < limit:
                consume(buffer)
            break

    return results


def fetch_search_results(
    query: str,
    content: str,
    base_url: str,
    timeout: float,
    *,
    language: str | None,
    file_format: str | None,
    limit: int,
    max_bytes: int,
    retries: int,
    overall_timeout: float = 90.0,
) -> tuple[list[dict[str, Any]], str]:
    params = urlencode({"q": query, "content": content})
    url = f"{base_url}/search?{params}"
    last_error: ClientError | None = None
    deadline = time.monotonic() + overall_timeout
    for attempt in range(1, retries + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ClientError("Search exceeded the configured overall safety deadline")
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
        try:
            response = open_request(
                request,
                timeout=min(timeout, remaining),
                allowed_redirect_hosts=ALLOWED_OFFICIAL_HOSTS,
            )
            with response:
                results = parse_streamed_search_response(
                    response,
                    base_url=base_url,
                    language=language,
                    file_format=file_format,
                    limit=limit,
                    max_bytes=max_bytes,
                    deadline=deadline,
                )
            return results, url
        except ClientError as exc:
            last_error = exc
            if attempt >= retries or "safety limit" in str(exc).lower():
                raise
            delay = min(2 ** (attempt - 1), 4, max(0.0, deadline - time.monotonic()))
            if delay:
                time.sleep(delay)
    raise last_error or ClientError("Search failed")


def command_search(args: argparse.Namespace) -> dict[str, Any]:
    base_url = normalize_official_base_url(args.base_url)
    if args.html_file:
        html_text = Path(args.html_file).read_text(encoding="utf-8")
        source_url = "local-fixture"
        results = parse_search_results(
            html_text,
            base_url=base_url,
            language=args.language,
            file_format=args.format,
            limit=args.limit,
        )
    else:
        results, source_url = fetch_search_results(
            args.query,
            args.content,
            base_url,
            args.timeout,
            language=args.language,
            file_format=args.format,
            limit=args.limit,
            max_bytes=args.max_search_bytes,
            retries=args.retries,
            overall_timeout=args.overall_timeout,
        )
    return {
        "status": "ok",
        "query": args.query,
        "source_url": source_url,
        "count": len(results),
        "results": results,
    }


def validate_md5(value: str) -> str:
    normalized = value.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{32}", normalized):
        raise ClientError("MD5 must contain exactly 32 hexadecimal characters")
    return normalized


def validate_format(value: str) -> str:
    normalized = value.strip().lower().lstrip(".")
    if normalized not in ALLOWED_FORMATS:
        raise ClientError(f"Unsupported file format: {normalized or '[empty]'}")
    return normalized


def fetch_download_descriptor(
    *,
    md5: str,
    secret: str,
    base_url: str,
    path_index: int | None,
    domain_index: int | None,
    timeout: float,
) -> dict[str, Any]:
    params: dict[str, Any] = {"md5": md5, "key": secret}
    if path_index is not None:
        params["path_index"] = path_index
    if domain_index is not None:
        params["domain_index"] = domain_index
    api_url = f"{base_url}/dyn/api/fast_download.json?{urlencode(params)}"
    request = Request(
        api_url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    response = open_request(
        request,
        timeout=timeout,
        allowed_redirect_hosts=ALLOWED_OFFICIAL_HOSTS,
        secret=secret,
    )
    with response:
        body = response.read(MAX_API_RESPONSE_BYTES + 1)
    if len(body) > MAX_API_RESPONSE_BYTES:
        raise ClientError("API response exceeded 1 MiB")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ClientError("Fast Download API returned invalid JSON") from None
    if not isinstance(payload, dict):
        raise ClientError("Fast Download API returned an unexpected JSON value")
    if not payload.get("download_url"):
        error = redact(str(payload.get("error") or "No download URL returned"), secret)
        raise ClientError(f"Fast Download API error: {error}")
    return payload


def clean_filename_part(value: str, fallback: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned or fallback


def safe_filename(
    title: str,
    file_format: str,
    *,
    authors: str = "",
    year: str = "",
    md5: str = "",
) -> str:
    author_part = clean_filename_part(authors, "未知作者")
    title_part = clean_filename_part(title, "未命名")
    year_part = clean_filename_part(year, "年份未知")
    md5_part = validate_md5(md5)[:8] if md5 else "无MD5"
    stem = f"{author_part} - {title_part} - {year_part} [{md5_part}]"
    # Keep room for a deep Skill directory on Windows installations that still
    # enforce the traditional MAX_PATH boundary.
    stem = stem[:120].strip(" .")
    return f"{stem}.{file_format}"


def validate_downloaded_file(path: Path, file_format: str, content_type: str) -> None:
    with path.open("rb") as handle:
        head = handle.read(512)
    lowered = head.lstrip().lower()
    if content_type.lower().startswith("text/html") or b"<html" in lowered[:200]:
        raise ClientError("Downloaded content is an HTML page, not the requested file")

    if file_format == "pdf" and not head.startswith(b"%PDF-"):
        raise ClientError("Downloaded file does not have a valid PDF signature")
    if file_format in {"mobi", "azw", "azw3"}:
        palm_signature = head[60:68] if len(head) >= 68 else b""
        if palm_signature not in {b"BOOKMOBI", b"TEXtREAd"}:
            raise ClientError(
                f"Downloaded file does not have a valid {file_format.upper()} signature"
            )
    if file_format in {"epub", "docx", "cbz", "zip"}:
        if not zipfile.is_zipfile(path):
            raise ClientError(f"Downloaded file is not a valid {file_format.upper()} ZIP container")
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > 100_000:
                raise ClientError("ZIP container has an unreasonable number of entries")
            expanded_size = sum(member.file_size for member in members)
            if expanded_size > max(path.stat().st_size * 100, 5 * 1024 * 1024 * 1024):
                raise ClientError("ZIP container has an unsafe expansion ratio")
            names = {member.filename for member in members}
            if file_format == "epub" and "META-INF/container.xml" not in names:
                raise ClientError("EPUB is missing META-INF/container.xml")
            if file_format == "epub":
                container = archive.getinfo("META-INF/container.xml")
                if container.file_size > 1_048_576:
                    raise ClientError("EPUB container metadata is unexpectedly large")
                archive.read(container)
            if file_format == "docx" and "[Content_Types].xml" not in names:
                raise ClientError("DOCX is missing [Content_Types].xml")
    if file_format == "djvu" and not head.startswith(b"AT&TFORM"):
        raise ClientError("Downloaded file does not have a valid DjVu signature")
    if file_format == "rtf" and not head.lstrip().startswith(b"{\\rtf"):
        raise ClientError("Downloaded file does not have a valid RTF signature")
    if file_format == "fb2" and b"<FictionBook" not in head and b"<fictionbook" not in lowered:
        raise ClientError("Downloaded file does not have a valid FB2 signature")
    if file_format == "txt":
        try:
            head.decode("utf-8")
        except UnicodeDecodeError:
            try:
                head.decode("gb18030")
            except UnicodeDecodeError:
                raise ClientError("Downloaded TXT does not use a supported text encoding") from None


def place_without_overwrite(temp_path: Path, output_dir: Path, filename: str) -> Path:
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    for index in range(1000):
        candidate_name = filename if index == 0 else f"{stem} ({index}){suffix}"
        candidate = output_dir / candidate_name
        try:
            os.link(temp_path, candidate)
            temp_path.unlink()
            return candidate
        except FileExistsError:
            continue
    raise ClientError("Could not choose a non-conflicting output filename")


def stream_download(
    *,
    download_url: str,
    output_dir: Path,
    title: str,
    authors: str,
    year: str,
    file_format: str,
    expected_md5: str,
    timeout: float,
    max_bytes: int,
    progress_interval: float = 0.0,
) -> dict[str, Any]:
    parsed = urlsplit(download_url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ClientError("Fast Download API returned a non-HTTPS or malformed URL")

    output_dir.mkdir(parents=True, exist_ok=True)
    part_path = output_dir / f".{expected_md5}.{file_format}.part"
    resume_from = part_path.stat().st_size if part_path.exists() else 0
    headers = {"User-Agent": USER_AGENT}
    if resume_from:
        headers["Range"] = f"bytes={resume_from}-"
    request = Request(download_url, headers=headers)
    response = open_request(
        request,
        timeout=timeout,
        allowed_redirect_hosts=None,
    )
    content_type = response.headers.get("Content-Type", "")
    content_length = response.headers.get("Content-Length", "")
    response_status = getattr(response, "status", 200)
    appending = bool(resume_from and response_status == 206)
    if resume_from and not appending:
        resume_from = 0
    expected_total = resume_from + int(content_length) if content_length.isdigit() else 0
    if expected_total and expected_total > max_bytes:
        response.close()
        raise ClientError("Download exceeds the configured maximum size")

    md5_hash = hashlib.md5(usedforsecurity=False)
    sha256_hash = hashlib.sha256()
    bytes_written = resume_from
    if appending:
        with part_path.open("rb") as existing:
            for chunk in iter(lambda: existing.read(1024 * 1024), b""):
                md5_hash.update(chunk)
                sha256_hash.update(chunk)
    started = time.monotonic()
    last_progress = started
    if resume_from and progress_interval:
        emit_progress(
            {
                "status": "download_progress",
                "resumed_bytes": resume_from,
                "downloaded_bytes": bytes_written,
                "expected_bytes": expected_total,
            }
        )
    try:
        with part_path.open("ab" if appending else "wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > max_bytes:
                    raise ClientError("Download exceeded the configured maximum size")
                output.write(chunk)
                md5_hash.update(chunk)
                sha256_hash.update(chunk)
                now = time.monotonic()
                if progress_interval and now - last_progress >= progress_interval:
                    progress: dict[str, Any] = {
                        "status": "download_progress",
                        "downloaded_bytes": bytes_written,
                        "expected_bytes": expected_total,
                    }
                    if expected_total:
                        progress["percent"] = round(bytes_written * 100 / expected_total, 1)
                    emit_progress(progress)
                    last_progress = now
            output.flush()
            os.fsync(output.fileno())
    except Exception as exc:
        # Keep the deterministic .part file so the next run can retry safely.
        raise ClientError(f"Download interrupted; partial file preserved: {type(exc).__name__}") from None
    finally:
        response.close()

    temp_path = part_path
    try:
        if not temp_path or not temp_path.exists():
            raise ClientError("Download did not create a temporary file")
        actual_md5 = md5_hash.hexdigest()
        if actual_md5 != expected_md5:
            raise ClientError(
                f"MD5 verification failed: expected {expected_md5}, got {actual_md5}"
            )
        validate_downloaded_file(temp_path, file_format, content_type)
        final_path = place_without_overwrite(
            temp_path,
            output_dir,
            safe_filename(
                title,
                file_format,
                authors=authors,
                year=year,
                md5=expected_md5,
            ),
        )
    except Exception:
        if temp_path and temp_path.exists():
            temp_path.unlink()
        raise

    elapsed = max(time.monotonic() - started, 0.001)
    return {
        "status": "downloaded",
        "path": str(final_path.resolve()),
        "bytes": bytes_written,
        "md5": actual_md5,
        "sha256": sha256_hash.hexdigest(),
        "content_type": content_type,
        "elapsed_seconds": round(elapsed, 3),
        "average_mib_per_second": round(bytes_written / 1024 / 1024 / elapsed, 3),
    }


def command_download(args: argparse.Namespace) -> dict[str, Any]:
    if not args.confirm_quota:
        raise ClientError("Download requires --confirm-quota after user confirmation")
    md5 = validate_md5(args.md5)
    file_format = validate_format(args.format)
    base_url = normalize_official_base_url(args.base_url)
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else DEFAULT_BOOKS_DIR
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    identity = f"[{md5[:8]}]"
    for candidate in output_dir.glob(f"*.{file_format}"):
        if identity not in candidate.name:
            continue
        if hash_file(candidate, "md5") == md5:
            return {
                "status": "existing",
                "path": str(candidate.resolve()),
                "bytes": candidate.stat().st_size,
                "md5": md5,
                "sha256": hash_file(candidate, "sha256"),
                "rights_basis": args.rights_basis,
                "attempts": 0,
                "api_quota_info_available": False,
            }
    secret = load_secret_key()

    last_error: ClientError | None = None
    descriptor: dict[str, Any] = {}
    for attempt in range(1, args.retries + 1):
        try:
            descriptor = fetch_download_descriptor(
                md5=md5,
                secret=secret,
                base_url=base_url,
                path_index=args.path_index,
                domain_index=args.domain_index,
                timeout=args.timeout,
            )
            result = stream_download(
                download_url=str(descriptor["download_url"]),
                output_dir=output_dir,
                title=args.title,
                authors=args.authors,
                year=args.year,
                file_format=file_format,
                expected_md5=md5,
                timeout=args.timeout,
                max_bytes=args.max_bytes,
                progress_interval=args.progress_interval,
            )
            result["attempts"] = attempt
            break
        except ClientError as exc:
            last_error = exc
            if attempt >= args.retries or any(
                marker in str(exc).lower()
                for marker in ("md5 verification", "invalid", "missing", "quota")
            ):
                raise
            time.sleep(min(2 ** (attempt - 1), 8))
    else:  # pragma: no cover - defensive loop boundary
        raise last_error or ClientError("Download failed")
    result["rights_basis"] = args.rights_basis
    result["api_quota_info_available"] = "account_fast_download_info" in descriptor
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Search and safely download explicitly authorized Anna's Archive records"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    search = subparsers.add_parser("search", help="Search the Full database web index")
    search.add_argument("--query", required=True)
    search.add_argument("--content", choices=CONTENT_TYPES, default="book_any")
    search.add_argument("--language", help="Language name or code, for example Chinese or zh")
    search.add_argument("--format", choices=sorted(ALLOWED_FORMATS))
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--base-url", default=DEFAULT_BASE_URL)
    search.add_argument("--timeout", type=float, default=45.0)
    search.add_argument("--overall-timeout", type=float, default=90.0)
    search.add_argument("--max-search-bytes", type=int, default=DEFAULT_MAX_SEARCH_BYTES)
    search.add_argument("--retries", type=int, default=2)
    search.add_argument("--html-file", help=argparse.SUPPRESS)
    search.set_defaults(handler=command_search)

    download = subparsers.add_parser("download", help="Download one authorized MD5 record")
    download.add_argument("--md5", required=True)
    download.add_argument("--title", required=True)
    download.add_argument("--format", required=True, choices=sorted(ALLOWED_FORMATS))
    download.add_argument("--authors", default="")
    download.add_argument("--year", default="")
    download.add_argument("--output-dir")
    download.add_argument("--rights-basis", required=True, choices=RIGHTS_BASES)
    download.add_argument("--confirm-quota", action="store_true")
    download.add_argument("--path-index", type=int)
    download.add_argument("--domain-index", type=int)
    download.add_argument("--base-url", default=DEFAULT_BASE_URL)
    download.add_argument("--timeout", type=float, default=3600.0)
    download.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_DOWNLOAD_BYTES)
    download.add_argument("--retries", type=int, default=3)
    download.add_argument("--progress-interval", type=float, default=5.0)
    download.set_defaults(handler=command_download)
    return parser


def validate_arguments(args: argparse.Namespace) -> None:
    if getattr(args, "limit", 1) < 1 or getattr(args, "limit", 1) > 100:
        raise ClientError("--limit must be between 1 and 100")
    if getattr(args, "timeout", 1) <= 0:
        raise ClientError("--timeout must be greater than zero")
    if getattr(args, "overall_timeout", 1) <= 0:
        raise ClientError("--overall-timeout must be greater than zero")
    progress_interval = getattr(args, "progress_interval", 0)
    if progress_interval < 0 or progress_interval > 300:
        raise ClientError("--progress-interval must be between 0 and 300 seconds")
    for name in ("path_index", "domain_index"):
        value = getattr(args, name, None)
        if value is not None and value < 0:
            raise ClientError(f"--{name.replace('_', '-')} must be zero or greater")
    if getattr(args, "max_bytes", 1) <= 0:
        raise ClientError("--max-bytes must be greater than zero")
    if getattr(args, "max_search_bytes", 1) <= 0:
        raise ClientError("--max-search-bytes must be greater than zero")
    if getattr(args, "retries", 1) < 1 or getattr(args, "retries", 1) > 5:
        raise ClientError("--retries must be between 1 and 5")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        validate_arguments(args)
        result = args.handler(args)
        emit_json(result)
        return 0
    except ClientError as exc:
        emit_json({"status": "error", "error": redact(str(exc))}, stream=sys.stderr)
        return 2
    except KeyboardInterrupt:
        emit_json({"status": "error", "error": "Operation cancelled"}, stream=sys.stderr)
        return 130
    except Exception as exc:  # Defensive final boundary: never expose raw URLs or keys.
        emit_json(
            {"status": "error", "error": f"Unexpected error: {redact(str(exc))}"},
            stream=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
