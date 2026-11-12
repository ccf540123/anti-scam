"""Server startup must not crawl or overwrite the local case files."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("REVIEW_PASSWORD", "test-review-pass")
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret-key-for-unit-tests")

import app as app_module
from modules import url_checker


class TestSafeStartup(unittest.TestCase):
    def test_serve_does_not_crawl_or_rewrite_cases(self):
        with patch.object(app_module.rag_searcher, "update_ptt_database") as update, patch.object(
            app_module.app, "run"
        ) as run:
            app_module.serve()

        update.assert_not_called()
        run.assert_called_once()
        self.assertEqual(run.call_args.kwargs.get("host"), "127.0.0.1")

    def test_165_download_does_not_overwrite_snapshot(self):
        snapshot = "weburl,normalized_url\nhttp://keep.example,keep.example\n"
        remote = "WEBURL\nhttps://downloaded.example/path\n"

        with self._temp_csv(snapshot) as temp_path:
            response = type("Response", (), {})()
            response.text = remote
            response.encoding = "utf-8-sig"
            response.raise_for_status = lambda: None

            with patch.object(url_checker, "LOCAL_165_CSV", str(temp_path)), patch.object(
                url_checker.requests, "get", return_value=response
            ) as get:
                loaded = url_checker.load_scam_urls("https://example.invalid/165.csv")

            get.assert_called_once()
            self.assertEqual(temp_path.read_text(encoding="utf-8"), snapshot)
            self.assertIn("downloaded.example", loaded)
            self.assertNotIn("keep.example", loaded)

    def test_165_download_failure_reads_snapshot_without_writing(self):
        snapshot = "weburl,normalized_url\nhttp://keep.example/a,keep.example\n"

        with self._temp_csv(snapshot) as temp_path:
            with patch.object(url_checker, "LOCAL_165_CSV", str(temp_path)), patch.object(
                url_checker.requests, "get", side_effect=OSError("offline")
            ):
                loaded = url_checker.load_scam_urls("https://example.invalid/165.csv")

            self.assertEqual(temp_path.read_text(encoding="utf-8"), snapshot)
            self.assertEqual(loaded, {"keep.example"})

    def _temp_csv(self, contents: str):
        import tempfile

        class _Holder:
            def __enter__(self_inner):
                self_inner._tmp = tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", suffix=".csv", delete=False
                )
                self_inner._tmp.write(contents)
                self_inner._tmp.close()
                return Path(self_inner._tmp.name)

            def __exit__(self_inner, exc_type, exc, tb):
                Path(self_inner._tmp.name).unlink(missing_ok=True)
                return False

        return _Holder()


if __name__ == "__main__":
    unittest.main()
