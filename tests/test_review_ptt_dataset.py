"""Review multi-dataset + PTT import tests (no live network)."""

from __future__ import annotations

import csv
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["REVIEW_PASSWORD"] = "test-review-pass"
os.environ["FLASK_SECRET_KEY"] = "test-secret-key-for-unit-tests"

from app import app  # noqa: E402
from modules import review_store  # noqa: E402
from scripts.import_ptt_candidates_to_review import (  # noqa: E402
    canonicalize_url,
    filter_rows,
    main as import_main,
    stable_review_id,
    to_review_item,
)


class TestImportPttCandidates(unittest.TestCase):
    def test_stable_id_from_url(self):
        a = stable_review_id("https://www.ptt.cc/bbs/Bunco/M.1.html")
        b = stable_review_id("https://www.ptt.cc/bbs/Bunco/M.1.html/")
        self.assertTrue(a.startswith("ptt_"))
        self.assertEqual(a, b)
        self.assertEqual(
            canonicalize_url("https://WWW.PTT.CC/bbs/Bunco/M.1.html/"),
            "https://www.ptt.cc/bbs/Bunco/M.1.html",
        )

    def test_filter_requires_explicit_selection_in_cli(self):
        with self.assertRaises(SystemExit):
            with patch("sys.argv", ["import_ptt_candidates_to_review.py"]):
                import_main()

    def test_import_limit_writes_independent_dataset(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "ptt_scam_cases.csv"
            out_dir = Path(tmp) / "ptt_candidates"
            with open(source, "w", encoding="utf-8-sig", newline="") as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=[
                        "title",
                        "url",
                        "content",
                        "source",
                        "published_at",
                        "source_board",
                        "search_keyword",
                    ],
                )
                writer.writeheader()
                for i in range(5):
                    writer.writerow(
                        {
                            "title": f"t{i}",
                            "url": f"https://www.ptt.cc/bbs/Bunco/M.{i}.html",
                            "content": f"body {i}",
                            "source": "ptt",
                            "published_at": "Mon Jan 1",
                            "source_board": "Bunco",
                            "search_keyword": "被騙",
                        }
                    )

            # 原始檔不該被改動：先記住內容
            original = source.read_text(encoding="utf-8-sig")

            with patch(
                "sys.argv",
                [
                    "import_ptt_candidates_to_review.py",
                    "--source",
                    str(source),
                    "--out-dir",
                    str(out_dir),
                    "--limit",
                    "2",
                ],
            ):
                import_main()

            self.assertEqual(source.read_text(encoding="utf-8-sig"), original)
            items_path = out_dir / "items.csv"
            self.assertTrue(items_path.exists())
            with open(items_path, encoding="utf-8-sig") as items_file:
                rows = list(csv.DictReader(items_file))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["dataset_type"], "ptt_candidate")
            self.assertTrue(rows[0]["review_id"].startswith("ptt_"))
            self.assertEqual(rows[0]["source_board"], "Bunco")
            self.assertEqual(rows[0]["search_keyword"], "被騙")
            self.assertTrue((out_dir / "answers.json").exists())


class TestReviewMultiDataset(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)

        self.fuzzy_csv = root / "fuzzy_items.csv"
        self.fuzzy_answers = root / "fuzzy_answers.json"
        self.ptt_csv = root / "ptt_items.csv"
        self.ptt_answers = root / "ptt_answers.json"

        self.fuzzy_csv.write_text(
            "\n".join(
                [
                    "review_id,shortener_host,title,article_url,published_at,extracted_url,normalized_url,match_reason,review_status,destination_opened,destination_type,is_scam_related_destination,human_notes,reviewer",
                    "1,reurl.cc,[新聞] 測試,https://www.ptt.cc/bbs/Bunco/M.1.html,Mon Jan 1,https://reurl.cc/abc,reurl.cc/abc,shortener,pending,,,,,",
                ]
            ),
            encoding="utf-8-sig",
        )
        # 預先寫一筆 Fuzzy 標註，確認不會被 PTT 存檔蓋掉
        self.fuzzy_answers.write_text(
            json.dumps(
                {
                    "1": {
                        "destination_opened": "yes",
                        "destination_type": "新聞",
                        "is_scam_related_destination": "no",
                        "human_notes": "keep-me",
                        "reviewer": "alice",
                        "review_status": "reviewed",
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        with open(self.ptt_csv, "w", encoding="utf-8-sig", newline="") as file:
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
                        "title": "[心得] 被騙經驗",
                        "url": "https://www.ptt.cc/bbs/Bunco/M.99.html",
                        "content": "我被騙了匯款",
                        "source": "ptt",
                        "published_at": "Tue Feb 2",
                        "source_board": "Bunco",
                        "search_keyword": "被騙",
                    },
                    "2026-01-01T00:00:00Z",
                )
            )
        self.ptt_answers.write_text("{}", encoding="utf-8")

        self.env = patch.dict(
            os.environ,
            {
                "REVIEW_PASSWORD": "test-review-pass",
                "REVIEW_ITEMS_CSV": str(self.fuzzy_csv),
                "REVIEW_ANSWERS_PATH": str(self.fuzzy_answers),
                "REVIEW_PTT_ITEMS_CSV": str(self.ptt_csv),
                "REVIEW_PTT_ANSWERS_PATH": str(self.ptt_answers),
            },
        )
        self.env.start()
        self.client.post(
            "/api/review/login",
            data=json.dumps({"password": "test-review-pass"}),
            content_type="application/json",
        )

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_list_datasets(self):
        response = self.client.get("/api/review/datasets")
        self.assertEqual(response.status_code, 200)
        ids = {d["id"] for d in response.get_json()["datasets"]}
        self.assertEqual(ids, {"fuzzy", "ptt_candidate"})

    def test_fuzzy_items_still_load_with_existing_answers(self):
        response = self.client.get("/api/review/items?dataset=fuzzy")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["dataset"]["id"], "fuzzy")
        self.assertEqual(len(payload["items"]), 1)
        item = payload["items"][0]
        self.assertEqual(item["destination_type"], "新聞")
        self.assertEqual(item["human_notes"], "keep-me")

    def test_ptt_items_and_article_type_save(self):
        items = self.client.get("/api/review/items?dataset=ptt_candidate")
        self.assertEqual(items.status_code, 200)
        payload = items.get_json()
        self.assertEqual(payload["dataset"]["kind"], "ptt_candidate")
        self.assertEqual(len(payload["items"]), 1)
        item = payload["items"][0]
        self.assertEqual(item["source_board"], "Bunco")
        self.assertEqual(item["search_keyword"], "被騙")
        self.assertIn("我被騙了匯款", item["content"])
        review_id = item["review_id"]

        saved = self.client.post(
            "/api/review/save",
            data=json.dumps(
                {
                    "dataset": "ptt_candidate",
                    "review_id": review_id,
                    "article_type": "個人被騙經驗",
                    "human_notes": "ok",
                    "reviewer": "bob",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(saved.status_code, 200)

        ptt_answers = review_store.load_answers("ptt_candidate")
        self.assertEqual(ptt_answers[str(review_id)]["article_type"], "個人被騙經驗")

        # Fuzzy answers 未被覆蓋
        fuzzy_answers = review_store.load_answers("fuzzy")
        self.assertEqual(fuzzy_answers["1"]["human_notes"], "keep-me")
        self.assertEqual(fuzzy_answers["1"]["destination_type"], "新聞")

    def test_empty_ptt_dataset_returns_empty_list(self):
        missing = Path(self.tmp.name) / "missing_ptt.csv"
        with patch.dict(
            os.environ,
            {"REVIEW_PTT_ITEMS_CSV": str(missing)},
        ):
            response = self.client.get("/api/review/items?dataset=ptt_candidate")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["items"], [])

    def test_filter_by_board(self):
        rows = [
            {
                "url": "https://www.ptt.cc/bbs/Bunco/M.1.html",
                "source_board": "Bunco",
                "search_keyword": "詐騙",
            },
            {
                "url": "https://www.ptt.cc/bbs/e-shopping/M.2.html",
                "source_board": "e-shopping",
                "search_keyword": "詐騙",
            },
        ]
        selected = filter_rows(rows, boards=["Bunco"], keywords=None, urls=None, limit=None)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["source_board"], "Bunco")


if __name__ == "__main__":
    unittest.main()
