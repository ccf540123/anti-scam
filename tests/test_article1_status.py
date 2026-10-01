"""Article 1 status: exact_match / temp (no early non_match)."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from crawlers.base import Article
from crawlers import ptt_crawler
from scripts.article1_status import (
    ARTICLE1_STATUS_EXACT_MATCH,
    ARTICLE1_STATUS_TEMP,
    classify_article1_status,
)
from scripts.ptt_165_cross_reference import run_cross_reference


class TestArticle1StatusHelper(unittest.TestCase):
    def test_exact_vs_temp(self):
        self.assertEqual(
            classify_article1_status(has_exact_url_match=True),
            ARTICLE1_STATUS_EXACT_MATCH,
        )
        self.assertEqual(
            classify_article1_status(has_exact_url_match=False),
            ARTICLE1_STATUS_TEMP,
        )


class TestCrawlerDefaultTemp(unittest.TestCase):
    def test_new_article_defaults_to_temp(self):
        art = Article(
            url="https://www.ptt.cc/bbs/Bunco/M.1.html",
            title="t",
            content="c",
            published_at="Mon",
            source="ptt",
        )
        self.assertEqual(art.status, "temp")

    def test_csv_includes_status_temp(self):
        art = Article(
            url="https://www.ptt.cc/bbs/Bunco/M.1.html",
            title="t",
            content="body",
            published_at="Mon",
            source="ptt",
            source_board="Bunco",
            search_keyword="詐騙",
            status="temp",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.csv"
            ptt_crawler.save_articles_to_csv([art], str(path))
            rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
            self.assertEqual(rows[0]["status"], "temp")
            self.assertIn("status", ptt_crawler.CSV_FIELDS)


class TestCrossReferenceNoEarlyNonMatch(unittest.TestCase):
    def test_no_url_match_becomes_temp_not_non_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ptt = tmp_path / "ptt.csv"
            scam = tmp_path / "165.csv"
            out = tmp_path / "out"

            with ptt.open("w", encoding="utf-8-sig", newline="") as file:
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
                writer.writerow(
                    {
                        "title": "[心得] 無官方網址",
                        "url": "https://www.ptt.cc/bbs/Bunco/M.temp.html",
                        "content": "我被騙了但沒有貼連結",
                        "source": "ptt",
                        "published_at": "Mon",
                        "source_board": "Bunco",
                        "search_keyword": "被騙",
                    }
                )
                writer.writerow(
                    {
                        "title": "[新聞] 有短網址",
                        "url": "https://www.ptt.cc/bbs/Bunco/M.fuzzy.html",
                        "content": "詳見 https://reurl.cc/abcd12 請小心",
                        "source": "ptt",
                        "published_at": "Tue",
                        "source_board": "Bunco",
                        "search_keyword": "詐騙",
                    }
                )
                writer.writerow(
                    {
                        "title": "[情報] exact",
                        "url": "https://www.ptt.cc/bbs/Bunco/M.exact.html",
                        "content": "網站 https://evil-scam-example.com/path 勿點",
                        "source": "ptt",
                        "published_at": "Wed",
                        "source_board": "Bunco",
                        "search_keyword": "詐騙",
                    }
                )

            with scam.open("w", encoding="utf-8-sig", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=["weburl", "normalized_url"])
                writer.writeheader()
                writer.writerow(
                    {
                        "weburl": "https://evil-scam-example.com",
                        "normalized_url": "evil-scam-example.com",
                    }
                )

            stats = run_cross_reference(str(ptt), str(scam), str(out), seed=42)

            # 不應再輸出 non_match 檔／類型
            self.assertFalse((out / "ptt_non_matches_sample.csv").exists())
            self.assertTrue((out / "ptt_temp_articles_sample.csv").exists())
            self.assertTrue((out / "ptt_fuzzy_matches_review.csv").exists())
            self.assertTrue((out / "ptt_exact_matches.csv").exists())
            self.assertTrue((out / "ptt_article1_status.csv").exists())

            temp_rows = list(
                csv.DictReader((out / "ptt_temp_articles_sample.csv").open(encoding="utf-8-sig"))
            )
            self.assertTrue(temp_rows)
            self.assertTrue(all(r["match_type"] == "temp" for r in temp_rows))
            self.assertFalse(any(r["match_type"] == "non_match" for r in temp_rows))

            fuzzy_rows = list(
                csv.DictReader((out / "ptt_fuzzy_matches_review.csv").open(encoding="utf-8-sig"))
            )
            self.assertEqual(len(fuzzy_rows), 1)
            self.assertEqual(fuzzy_rows[0]["match_type"], "fuzzy_match")

            status_rows = list(
                csv.DictReader((out / "ptt_article1_status.csv").open(encoding="utf-8-sig"))
            )
            by_url = {r["url"]: r for r in status_rows}
            self.assertEqual(by_url["https://www.ptt.cc/bbs/Bunco/M.temp.html"]["status"], "temp")
            self.assertEqual(by_url["https://www.ptt.cc/bbs/Bunco/M.fuzzy.html"]["status"], "temp")
            self.assertEqual(
                by_url["https://www.ptt.cc/bbs/Bunco/M.exact.html"]["status"], "exact_match"
            )
            # 原始欄位保留
            self.assertEqual(
                by_url["https://www.ptt.cc/bbs/Bunco/M.temp.html"]["source_board"], "Bunco"
            )
            self.assertEqual(
                by_url["https://www.ptt.cc/bbs/Bunco/M.temp.html"]["search_keyword"], "被騙"
            )

            self.assertEqual(stats["article1_exact_match_articles"], 1)
            self.assertEqual(stats["article1_temp_articles"], 2)
            self.assertNotIn("non_match_articles", stats)


if __name__ == "__main__":
    unittest.main()
