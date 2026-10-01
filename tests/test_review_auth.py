"""Review password gate tests (no live network)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure env before importing app
os.environ["REVIEW_PASSWORD"] = "test-review-pass"
os.environ["FLASK_SECRET_KEY"] = "test-secret-key-for-unit-tests"

from app import app  # noqa: E402
from modules import review_store  # noqa: E402


class TestReviewAuth(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.tmp = tempfile.TemporaryDirectory()
        self.items_csv = Path(self.tmp.name) / "items.csv"
        self.answers = Path(self.tmp.name) / "answers.json"
        self.items_csv.write_text(
            "\n".join(
                [
                    "review_id,shortener_host,title,article_url,published_at,extracted_url,normalized_url,match_reason,review_status,destination_opened,destination_type,is_scam_related_destination,human_notes,reviewer",
                    "1,reurl.cc,[新聞] 測試,https://www.ptt.cc/bbs/Bunco/M.1.html,Mon Jan 1,https://reurl.cc/abc,reurl.cc/abc,shortener,pending,,,,,",
                ]
            ),
            encoding="utf-8-sig",
        )
        self.env = patch.dict(
            os.environ,
            {
                "REVIEW_PASSWORD": "test-review-pass",
                "REVIEW_ITEMS_CSV": str(self.items_csv),
                "REVIEW_ANSWERS_PATH": str(self.answers),
            },
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_items_require_login(self):
        response = self.client.get("/api/review/items")
        self.assertEqual(response.status_code, 401)

    def test_login_and_fetch_items(self):
        bad = self.client.post(
            "/api/review/login",
            data=json.dumps({"password": "wrong"}),
            content_type="application/json",
        )
        self.assertEqual(bad.status_code, 401)

        ok = self.client.post(
            "/api/review/login",
            data=json.dumps({"password": "test-review-pass"}),
            content_type="application/json",
        )
        self.assertEqual(ok.status_code, 200)

        items = self.client.get("/api/review/items")
        self.assertEqual(items.status_code, 200)
        payload = items.get_json()
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["review_id"], 1)

    def test_save_answer(self):
        self.client.post(
            "/api/review/login",
            data=json.dumps({"password": "test-review-pass"}),
            content_type="application/json",
        )
        saved = self.client.post(
            "/api/review/save",
            data=json.dumps(
                {
                    "review_id": 1,
                    "destination_opened": "yes",
                    "destination_type": "新聞",
                    "is_scam_related_destination": "no",
                    "human_notes": "ok",
                    "reviewer": "tester",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(saved.status_code, 200)
        answers = review_store.load_answers()
        self.assertEqual(answers["1"]["destination_type"], "新聞")
        self.assertEqual(answers["1"]["review_status"], "reviewed")

    def test_public_home_still_works(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
