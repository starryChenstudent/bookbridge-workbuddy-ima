from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "annas_archive_client", SCRIPTS / "annas_archive_client.py"
)
assert SPEC and SPEC.loader
CLIENT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLIENT)


class RecordDiscoveryTests(unittest.TestCase):
    def test_official_record_url_is_normalized_to_md5(self) -> None:
        value = "https://annas-archive.gl/md5/0123456789ABCDEF0123456789ABCDEF"
        self.assertEqual(
            CLIENT.record_reference_to_md5(value),
            "0123456789abcdef0123456789abcdef",
        )

    def test_unofficial_or_decorated_record_url_is_rejected(self) -> None:
        invalid = (
            "https://example.com/md5/0123456789abcdef0123456789abcdef",
            "https://annas-archive.gl/md5/0123456789abcdef0123456789abcdef?key=secret",
            "http://annas-archive.gl/md5/0123456789abcdef0123456789abcdef",
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(CLIENT.ClientError):
                CLIENT.record_reference_to_md5(value)

    def test_record_cache_round_trip_uses_normalized_exact_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = Path(temp_dir) / "records.json"
            with mock.patch.dict(os.environ, {"BOOKBRIDGE_RECORD_CACHE": str(cache)}):
                CLIENT.remember_record(
                    {
                        "title": "《测试书》",
                        "authors": "作者甲",
                        "publisher": "测试出版社",
                        "year": "2026",
                        "language": "zh",
                        "format": "pdf",
                        "md5": "0123456789abcdef0123456789abcdef",
                        "record_url": "https://annas-archive.gl/md5/0123456789abcdef0123456789abcdef",
                    }
                )
                matches = CLIENT.find_cached_records("测试书", authors="作者甲")

            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0]["format"], "pdf")
            self.assertEqual(cache.stat().st_mode & 0o777, 0o600)
            payload = json.loads(cache.read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], 1)

    def test_unknown_title_has_no_cached_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = Path(temp_dir) / "records.json"
            with mock.patch.dict(os.environ, {"BOOKBRIDGE_RECORD_CACHE": str(cache)}):
                self.assertEqual(CLIENT.find_cached_records("从未保存的书"), [])

    def test_auto_format_detects_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "download.part"
            path.write_bytes(b"%PDF-1.7\n")
            self.assertEqual(CLIENT.detect_downloaded_format(path), "pdf")

    def test_auto_format_detects_epub(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "download.part"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("META-INF/container.xml", "<container/>")
            self.assertEqual(CLIENT.detect_downloaded_format(path), "epub")


if __name__ == "__main__":
    unittest.main()
