"""Review password gate tests (no live network)."""

from __future__ import annotations

import csv
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
from scripts.import_ptt_candidates_to_review import to_review_item  # noqa: E402


class TestReviewAuth(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.tmp = tempfile.TemporaryDirectory()
        self.items_csv = Path(self.tmp.name) / "items.csv"
        self.answers = Path(self.tmp.name) / "answers.json"
        with open(self.items_csv, "w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=[
                    "review_id",
                    "dataset_type",
                    "dedup_key",
                    "title",
                    "article_url",
                    "content",
                    "published_at",
                    "source",
                    "source_board",
                    "search_keyword",
                    "imported_at",
                    "review_status",
                    "status",
                    "article_type",
                    "human_notes",
                    "reviewer",
                ],
            )
            writer.writeheader()
            writer.writerow(
                to_review_item(
                    {
                        "title": "[心得] 測試",
                        "url": "https://www.ptt.cc/bbs/Bunco/M.1.html",
                        "content": "我被騙了",
                        "source": "ptt",
                        "published_at": "Mon Jan 1",
                        "source_board": "Bunco",
                        "search_keyword": "被騙",
                    },
                    "2026-01-01T00:00:00Z",
                )
            )
        self.env = patch.dict(
            os.environ,
            {
                "REVIEW_PASSWORD": "test-review-pass",
                "REVIEW_PTT_ITEMS_CSV": str(self.items_csv),
                "REVIEW_PTT_ANSWERS_PATH": str(self.answers),
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
        self.assertEqual(payload["dataset"]["id"], "ptt_candidate")
        self.assertEqual(len(payload["items"]), 1)
        self.assertTrue(str(payload["items"][0]["review_id"]).startswith("ptt_"))

    def test_save_answer(self):
        self.client.post(
            "/api/review/login",
            data=json.dumps({"password": "test-review-pass"}),
            content_type="application/json",
        )
        items = self.client.get("/api/review/items").get_json()["items"]
        review_id = items[0]["review_id"]
        saved = self.client.post(
            "/api/review/save",
            data=json.dumps(
                {
                    "dataset": "ptt_candidate",
                    "review_id": review_id,
                    "content_relevant": "yes",
                    "url_relevant": "no",
                    "keywords": ["假投資"],
                    "human_notes": "ok",
                    "reviewer": "tester",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(saved.status_code, 200)
        answers = review_store.load_answers("ptt_candidate")
        self.assertEqual(answers[str(review_id)]["keywords"], ["假投資"])
        self.assertEqual(answers[str(review_id)]["status"], "temp")
        self.assertEqual(answers[str(review_id)]["review_status"], "reviewed")

    def test_public_home_still_works(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
