"""第一階段 pipeline：重用既有模組、只 append temp、不碰 answers。"""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from crawlers.base import Article
from scripts.article1_status import (
    ARTICLE1_STATUS_EXACT_MATCH,
    ARTICLE1_STATUS_TEMP,
)
from scripts.import_ptt_candidates_to_review import stable_review_id
from scripts.ptt_stage1_pipeline import (
    append_temp_rows_to_review,
    commit_and_push_review_items,
    count_article1_statuses,
    main as pipeline_main,
    run_stage1_pipeline,
    select_temp_rows,
)


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


class TestSelectTempRows(unittest.TestCase):
    def test_only_temp_selected_exact_excluded(self):
        rows = [
            {"url": "https://www.ptt.cc/bbs/Bunco/M.1.html", "status": "temp", "title": "a"},
            {
                "url": "https://www.ptt.cc/bbs/Bunco/M.2.html",
                "status": "exact_match",
                "title": "b",
            },
            {"url": "https://www.ptt.cc/bbs/Bunco/M.3.html", "status": "temp", "title": "c"},
            {
                "url": "https://www.ptt.cc/bbs/Bunco/M.1.html/",
                "status": "temp",
                "title": "dup",
            },
            {"url": "https://www.ptt.cc/bbs/Bunco/M.4.html", "status": "non_match", "title": "x"},
        ]
        selected = select_temp_rows(rows)
        urls = [row["url"] for row in selected]
        self.assertEqual(len(selected), 2)
        self.assertIn("https://www.ptt.cc/bbs/Bunco/M.1.html", urls)
        self.assertIn("https://www.ptt.cc/bbs/Bunco/M.3.html", urls)
        self.assertNotIn("https://www.ptt.cc/bbs/Bunco/M.2.html", urls)

    def test_status_counts(self):
        rows = [
            {"status": "temp"},
            {"status": "exact_match"},
            {"status": "temp"},
            {"status": ""},
        ]
        counts = count_article1_statuses(rows)
        self.assertEqual(counts["temp"], 2)
        self.assertEqual(counts["exact_match"], 1)
        self.assertEqual(counts["other"], 1)


class TestAppendTempToReview(unittest.TestCase):
    def test_append_keeps_existing_and_skips_dupes_and_answers(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "ptt_candidates"
            out_dir.mkdir()
            existing_url = "https://www.ptt.cc/bbs/Bunco/M.old.html"
            existing_id = stable_review_id(existing_url)
            _write_csv(
                out_dir / "items.csv",
                [
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
                [
                    {
                        "review_id": existing_id,
                        "dataset_type": "ptt_candidate",
                        "dedup_key": existing_url,
                        "title": "old-title",
                        "article_url": existing_url,
                        "content": "old-content",
                        "published_at": "Mon",
                        "source": "ptt",
                        "source_board": "Bunco",
                        "search_keyword": "詐騙",
                        "imported_at": "2026-01-01T00:00:00Z",
                        "review_status": "pending",
                        "status": "temp",
                        "article_type": "",
                        "human_notes": "keep-me",
                        "reviewer": "alice",
                    }
                ],
            )
            answers_path = out_dir / "answers.json"
            answers_path.write_text(
                json.dumps(
                    {
                        existing_id: {
                            "content_relevant": "yes",
                            "url_relevant": "no",
                            "keywords": ["人工詞"],
                            "status": "temp",
                            "review_status": "reviewed",
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            before_answers = answers_path.read_text(encoding="utf-8")

            temp_rows = [
                {
                    "title": "old-should-skip",
                    "url": existing_url,
                    "content": "new-should-not-overwrite",
                    "source": "ptt",
                    "published_at": "Tue",
                    "source_board": "Bunco",
                    "search_keyword": "被騙",
                    "status": "temp",
                },
                {
                    "title": "brand-new",
                    "url": "https://www.ptt.cc/bbs/Bunco/M.new.html",
                    "content": "new body",
                    "source": "ptt",
                    "published_at": "Wed",
                    "source_board": "Bunco",
                    "search_keyword": "匯款",
                    "status": "temp",
                },
                {
                    "title": "exact-must-not-import",
                    "url": "https://www.ptt.cc/bbs/Bunco/M.exact.html",
                    "content": "exact",
                    "source": "ptt",
                    "published_at": "Thu",
                    "source_board": "Bunco",
                    "search_keyword": "詐騙",
                    "status": "exact_match",
                },
            ]
            # append helper 只吃已篩好的 temp；此測模擬呼叫端只傳 temp
            only_temp = [row for row in temp_rows if row["status"] == "temp"]
            info = append_temp_rows_to_review(only_temp, out_dir=out_dir)

            self.assertEqual(info["added"], 1)
            self.assertEqual(info["skipped_existing"], 1)
            self.assertEqual(info["items_total"], 2)

            with open(out_dir / "items.csv", encoding="utf-8-sig", newline="") as file:
                items = list(csv.DictReader(file))
            by_url = {row["article_url"]: row for row in items}
            self.assertEqual(by_url[existing_url]["title"], "old-title")
            self.assertEqual(by_url[existing_url]["content"], "old-content")
            self.assertEqual(by_url[existing_url]["human_notes"], "keep-me")
            self.assertEqual(
                by_url["https://www.ptt.cc/bbs/Bunco/M.new.html"]["status"],
                ARTICLE1_STATUS_TEMP,
            )
            self.assertNotIn("https://www.ptt.cc/bbs/Bunco/M.exact.html", by_url)

            after_answers = answers_path.read_text(encoding="utf-8")
            self.assertEqual(before_answers, after_answers)


class TestRunStage1Pipeline(unittest.TestCase):
    def test_pipeline_skip_crawl_and_xref_uses_article1_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ptt_csv = root / "ptt_scam_cases.csv"
            xref_dir = root / "xref"
            review_dir = root / "ptt_candidates"
            xref_dir.mkdir()

            _write_csv(
                ptt_csv,
                ["title", "url", "content", "source", "published_at"],
                [
                    {
                        "title": "t1",
                        "url": "https://www.ptt.cc/bbs/Bunco/M.1.html",
                        "content": "c1",
                        "source": "ptt",
                        "published_at": "Mon",
                    }
                ],
            )
            _write_csv(
                xref_dir / "ptt_article1_status.csv",
                [
                    "title",
                    "url",
                    "content",
                    "source",
                    "published_at",
                    "source_board",
                    "search_keyword",
                    "status",
                    "status_reason",
                ],
                [
                    {
                        "title": "temp-a",
                        "url": "https://www.ptt.cc/bbs/Bunco/M.temp.html",
                        "content": "body",
                        "source": "ptt",
                        "published_at": "Mon",
                        "source_board": "Bunco",
                        "search_keyword": "詐騙",
                        "status": ARTICLE1_STATUS_TEMP,
                        "status_reason": "no_exact_url_match_waiting_human_review",
                    },
                    {
                        "title": "exact-b",
                        "url": "https://www.ptt.cc/bbs/Bunco/M.exact.html",
                        "content": "body",
                        "source": "ptt",
                        "published_at": "Mon",
                        "source_board": "Bunco",
                        "search_keyword": "詐騙",
                        "status": ARTICLE1_STATUS_EXACT_MATCH,
                        "status_reason": "official_url_exact_match",
                    },
                ],
            )

            result = run_stage1_pipeline(
                ptt_csv=str(ptt_csv),
                xref_output_dir=str(xref_dir),
                review_out_dir=str(review_dir),
                skip_crawl=True,
                skip_xref=True,
            )

            self.assertEqual(result["summary"]["爬蟲文章"], 1)
            self.assertEqual(result["summary"]["exact_match"], 1)
            self.assertEqual(result["summary"]["temp"], 1)
            self.assertEqual(result["summary"]["新增 Review"], 1)
            self.assertEqual(result["summary"]["已存在／跳過"], 0)

            with open(review_dir / "items.csv", encoding="utf-8-sig", newline="") as file:
                items = list(csv.DictReader(file))
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["status"], "temp")
            self.assertEqual(
                items[0]["article_url"],
                "https://www.ptt.cc/bbs/Bunco/M.temp.html",
            )
            self.assertTrue((review_dir / "answers.json").exists())
            self.assertEqual(
                (review_dir / "answers.json").read_text(encoding="utf-8").strip(),
                "{}",
            )

    def test_pipeline_calls_crawl_and_xref_when_not_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ptt_csv = root / "ptt_scam_cases.csv"
            xref_dir = root / "xref"
            review_dir = root / "ptt_candidates"

            fake_articles = [
                Article(
                    title="t",
                    url="https://www.ptt.cc/bbs/Bunco/M.live.html",
                    content="c",
                    source="ptt",
                    published_at="Mon",
                    source_board="Bunco",
                    search_keyword="詐騙",
                    status="temp",
                )
            ]
            fake_summary = {
                "boards": ["Bunco"],
                "keywords": ["詐騙"],
                "pages": 1,
                "per_combo": [],
                "total_before_dedup": 1,
                "total_after_dedup": 1,
                "board_counts": {"Bunco": 1},
                "possible_case_type_counts": {},
                "failures": [],
            }

            def fake_xref(ptt, csv_a, csv_b, output_dir, seed=42):
                out = Path(output_dir)
                out.mkdir(parents=True, exist_ok=True)
                _write_csv(
                    out / "ptt_article1_status.csv",
                    ["title", "url", "content", "source", "published_at", "status"],
                    [
                        {
                            "title": "t",
                            "url": "https://www.ptt.cc/bbs/Bunco/M.live.html",
                            "content": "c",
                            "source": "ptt",
                            "published_at": "Mon",
                            "status": "temp",
                        }
                    ],
                )
                return {
                    "ptt_article_count": 1,
                    "article1_exact_match_articles": 0,
                    "article1_temp_articles": 1,
                    "output_files": [str(out / "ptt_article1_status.csv")],
                }

            with patch(
                "scripts.ptt_stage1_pipeline.crawl_ptt_multi",
                return_value=(fake_articles, fake_summary),
            ) as mock_crawl, patch(
                "scripts.ptt_stage1_pipeline.run_dual_source",
                side_effect=fake_xref,
            ) as mock_xref:
                result = run_stage1_pipeline(
                    pages=1,
                    ptt_csv=str(ptt_csv),
                    csv_176455=str(root / "a.csv"),
                    csv_160055=str(root / "b.csv"),
                    xref_output_dir=str(xref_dir),
                    review_out_dir=str(review_dir),
                    skip_crawl=False,
                    skip_xref=False,
                )

            mock_crawl.assert_called_once()
            mock_xref.assert_called_once()
            self.assertTrue(ptt_csv.exists())
            self.assertEqual(result["summary"]["新增 Review"], 1)
            self.assertEqual(result["summary"]["temp"], 1)

    def test_pipeline_stops_when_crawl_returns_zero_articles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ptt_csv = root / "ptt_scam_cases.csv"
            # 舊 CSV 存在：空爬蟲時不可拿它繼續比對／匯入
            _write_csv(
                ptt_csv,
                ["title", "url", "content", "source", "published_at"],
                [
                    {
                        "title": "stale",
                        "url": "https://www.ptt.cc/bbs/Bunco/M.stale.html",
                        "content": "old",
                        "source": "ptt",
                        "published_at": "Mon",
                    }
                ],
            )
            xref_dir = root / "xref"
            review_dir = root / "ptt_candidates"
            review_dir.mkdir()
            _write_csv(
                review_dir / "items.csv",
                [
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
                [],
            )
            answers_path = review_dir / "answers.json"
            answers_path.write_text('{"keep": true}', encoding="utf-8")
            before_answers = answers_path.read_text(encoding="utf-8")
            before_items = (review_dir / "items.csv").read_text(encoding="utf-8")

            empty_summary = {
                "boards": ["Bunco"],
                "keywords": ["詐騙"],
                "pages": 1,
                "per_combo": [],
                "total_before_dedup": 0,
                "total_after_dedup": 0,
                "board_counts": {},
                "possible_case_type_counts": {},
                "failures": [],
            }

            with patch(
                "scripts.ptt_stage1_pipeline.crawl_ptt_multi",
                return_value=([], empty_summary),
            ) as mock_crawl, patch(
                "scripts.ptt_stage1_pipeline.run_dual_source"
            ) as mock_xref, patch(
                "scripts.ptt_stage1_pipeline.append_temp_rows_to_review"
            ) as mock_import:
                result = run_stage1_pipeline(
                    pages=1,
                    ptt_csv=str(ptt_csv),
                    csv_176455=str(root / "a.csv"),
                    csv_160055=str(root / "b.csv"),
                    xref_output_dir=str(xref_dir),
                    review_out_dir=str(review_dir),
                    skip_crawl=False,
                    skip_xref=False,
                )

            mock_crawl.assert_called_once()
            mock_xref.assert_not_called()
            mock_import.assert_not_called()
            self.assertTrue(result.get("stopped"))
            self.assertIn("沒有成功爬到文章", result.get("stop_reason", ""))
            self.assertEqual(result["summary"]["爬蟲文章"], 0)
            self.assertEqual(result["summary"]["新增 Review"], 0)
            self.assertEqual(
                answers_path.read_text(encoding="utf-8"),
                before_answers,
            )
            self.assertEqual(
                (review_dir / "items.csv").read_text(encoding="utf-8"),
                before_items,
            )
            # 舊 CSV 仍在，但後續流程未使用它寫入新 xref/import
            self.assertFalse((xref_dir / "ptt_article1_status.csv").exists())

    def test_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review_dir = root / "ptt_candidates"
            result = pipeline_main(
                [
                    "--dry-run",
                    "--review-out-dir",
                    str(review_dir),
                ]
            )
            self.assertIsNone(result)
            self.assertFalse(review_dir.exists())

    def test_main_zero_crawl_does_not_commit_or_push(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ptt_csv = root / "ptt_scam_cases.csv"
            review_dir = root / "ptt_candidates"
            empty_summary = {
                "boards": ["Bunco"],
                "keywords": ["詐騙"],
                "pages": 1,
                "per_combo": [],
                "total_before_dedup": 0,
                "total_after_dedup": 0,
                "board_counts": {},
                "possible_case_type_counts": {},
                "failures": [],
            }
            with patch(
                "scripts.ptt_stage1_pipeline.crawl_ptt_multi",
                return_value=([], empty_summary),
            ), patch(
                "scripts.ptt_stage1_pipeline.commit_and_push_review_items"
            ) as mock_git:
                result = pipeline_main(
                    [
                        "--ptt-csv",
                        str(ptt_csv),
                        "--review-out-dir",
                        str(review_dir),
                        "--xref-output-dir",
                        str(root / "xref"),
                    ]
                )
            self.assertTrue(result.get("stopped"))
            mock_git.assert_not_called()
            self.assertNotIn("git", result)

    def test_main_success_auto_commit_push(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ptt_csv = root / "ptt_scam_cases.csv"
            xref_dir = root / "xref"
            review_dir = root / "ptt_candidates"
            xref_dir.mkdir()
            _write_csv(
                ptt_csv,
                ["title", "url", "content", "source", "published_at"],
                [
                    {
                        "title": "t",
                        "url": "https://www.ptt.cc/bbs/Bunco/M.1.html",
                        "content": "c",
                        "source": "ptt",
                        "published_at": "Mon",
                    }
                ],
            )
            _write_csv(
                xref_dir / "ptt_article1_status.csv",
                ["title", "url", "content", "source", "published_at", "status"],
                [
                    {
                        "title": "t",
                        "url": "https://www.ptt.cc/bbs/Bunco/M.1.html",
                        "content": "c",
                        "source": "ptt",
                        "published_at": "Mon",
                        "status": "temp",
                    }
                ],
            )
            with patch(
                "scripts.ptt_stage1_pipeline.commit_and_push_review_items",
                return_value={
                    "committed": True,
                    "pushed": True,
                    "reason": "ok",
                    "path": "data/review/ptt_candidates/items.csv",
                    "branch": "main",
                },
            ) as mock_git:
                result = pipeline_main(
                    [
                        "--skip-crawl",
                        "--skip-xref",
                        "--ptt-csv",
                        str(ptt_csv),
                        "--xref-output-dir",
                        str(xref_dir),
                        "--review-out-dir",
                        str(review_dir),
                    ]
                )
            mock_git.assert_called_once()
            self.assertTrue(result["git"]["pushed"])

    def test_commit_and_push_helper_stages_only_items(self):
        calls: list[list[str]] = []

        def fake_run(cmd, check=False, **kwargs):
            calls.append(list(cmd))
            class Result:
                returncode = 1 if cmd[:3] == ["git", "diff", "--cached"] else 0
            if cmd[:2] == ["git", "diff"]:
                return Result()
            return Result()

        with tempfile.TemporaryDirectory() as tmp:
            items = Path(tmp) / "items.csv"
            items.write_text("review_id\n1\n", encoding="utf-8")
            pages = Path(tmp) / "docs" / "review" / "items.csv"
            with patch(
                "scripts.ptt_stage1_pipeline.subprocess.run",
                side_effect=fake_run,
            ), patch(
                "scripts.ptt_stage1_pipeline.PAGES_REVIEW_ITEMS_CSV",
                pages,
            ):
                info = commit_and_push_review_items(items, branch="main")
            self.assertTrue(info["committed"])
            self.assertTrue(info["pushed"])
            self.assertTrue(pages.exists())
            self.assertEqual(calls[0][:2], ["git", "add"])
            self.assertIn("commit", calls[2])
            self.assertEqual(calls[3], ["git", "push", "origin", "main"])


if __name__ == "__main__":
    unittest.main()
