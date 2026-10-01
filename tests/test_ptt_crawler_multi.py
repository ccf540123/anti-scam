"""PTT multi-board / multi-keyword crawler unit tests (mocked; no live PTT)."""

from __future__ import annotations

import csv
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from crawlers.base import Article
from crawlers import ptt_crawler
from modules import rag_searcher


def _article(
    url: str,
    title: str,
    board: str,
    keyword: str,
    content: str = "正文內容完整保留",
) -> Article:
    return Article(
        url=url,
        title=title,
        content=content,
        published_at="Mon Jan 1 00:00:00 2026",
        source="ptt",
        source_board=board,
        search_keyword=keyword,
        search_page="1",
        crawl_time="2026-01-01T00:00:00Z",
        dedup_key=ptt_crawler.canonicalize_url(url),
        review_status="unreviewed",
        possible_case_type=ptt_crawler.guess_possible_case_type(title, content),
    )


class TestPttCrawlerMulti(unittest.TestCase):
    def test_legacy_single_board_keyword_defaults(self):
        ns = MagicMock()
        ns.boards = None
        ns.board = None
        ns.keywords = None
        ns.keyword = None
        boards, keywords = ptt_crawler.parse_boards_and_keywords(ns)
        self.assertEqual(boards, ["Bunco"])
        self.assertEqual(keywords, ["詐騙"])

    def test_legacy_keyword_append_still_works(self):
        ns = MagicMock()
        ns.boards = None
        ns.board = ["Bunco"]
        ns.keywords = None
        ns.keyword = ["詐騙"]
        boards, keywords = ptt_crawler.parse_boards_and_keywords(ns)
        self.assertEqual(boards, ["Bunco"])
        self.assertEqual(keywords, ["詐騙"])

    def test_multi_boards_keywords_expand_all_combinations(self):
        with patch.object(ptt_crawler, "crawl_ptt_search") as mocked:
            mocked.side_effect = [
                (
                    [_article("https://www.ptt.cc/bbs/Bunco/M.1.A.1.html", "A", "Bunco", "詐騙")],
                    {
                        "raw_listings": 1,
                        "fetch_success": 1,
                        "pages_fetched": 1,
                        "failed": False,
                        "error": "",
                    },
                ),
                (
                    [_article("https://www.ptt.cc/bbs/Bunco/M.2.A.2.html", "B", "Bunco", "被騙")],
                    {
                        "raw_listings": 1,
                        "fetch_success": 1,
                        "pages_fetched": 1,
                        "failed": False,
                        "error": "",
                    },
                ),
                (
                    [
                        _article(
                            "https://www.ptt.cc/bbs/e-shopping/M.3.A.3.html",
                            "C",
                            "e-shopping",
                            "詐騙",
                        )
                    ],
                    {
                        "raw_listings": 1,
                        "fetch_success": 1,
                        "pages_fetched": 1,
                        "failed": False,
                        "error": "",
                    },
                ),
                (
                    [
                        _article(
                            "https://www.ptt.cc/bbs/e-shopping/M.4.A.4.html",
                            "D",
                            "e-shopping",
                            "被騙",
                        )
                    ],
                    {
                        "raw_listings": 1,
                        "fetch_success": 1,
                        "pages_fetched": 1,
                        "failed": False,
                        "error": "",
                    },
                ),
            ]
            articles, summary = ptt_crawler.crawl_ptt_multi(
                boards=["Bunco", "e-shopping"],
                keywords=["詐騙", "被騙"],
                pages=1,
            )
            self.assertEqual(mocked.call_count, 4)
            called = [
                (c.kwargs["board"], c.kwargs["keyword"]) for c in mocked.call_args_list
            ]
            self.assertEqual(
                called,
                [
                    ("Bunco", "詐騙"),
                    ("Bunco", "被騙"),
                    ("e-shopping", "詐騙"),
                    ("e-shopping", "被騙"),
                ],
            )
            self.assertEqual(len(articles), 4)
            self.assertEqual(summary["total_after_dedup"], 4)

    def test_same_url_kept_once_across_keywords(self):
        url = "https://www.ptt.cc/bbs/Bunco/M.100.A.ABC.html"
        a1 = _article(url, "同一篇", "Bunco", "詐騙")
        a2 = _article(url, "同一篇", "Bunco", "被騙")
        a3 = _article(url, "同一篇", "Bunco", "匯款")
        merged = ptt_crawler.merge_articles_by_dedup([a1, a2, a3])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].search_keyword, "詐騙、被騙、匯款")
        self.assertEqual(merged[0].source_board, "Bunco")

    def test_source_board_and_search_keyword_recorded(self):
        art = _article(
            "https://www.ptt.cc/bbs/Bank_Service/M.9.A.9.html",
            "測試",
            "Bank_Service",
            "匯款",
        )
        self.assertEqual(art.source_board, "Bank_Service")
        self.assertEqual(art.search_keyword, "匯款")

    def test_one_combo_failure_continues_others(self):
        def side_effect(board, keyword, pages, delay_sec):
            if board == "Bunco" and keyword == "被騙":
                raise RuntimeError("boom")
            return (
                [_article(f"https://www.ptt.cc/bbs/{board}/M.{keyword}.html", keyword, board, keyword)],
                {
                    "raw_listings": 1,
                    "fetch_success": 1,
                    "pages_fetched": 1,
                    "failed": False,
                    "error": "",
                },
            )

        with patch.object(ptt_crawler, "crawl_ptt_search", side_effect=side_effect):
            articles, summary = ptt_crawler.crawl_ptt_multi(
                boards=["Bunco"],
                keywords=["詐騙", "被騙", "匯款"],
                pages=1,
            )
        self.assertEqual(len(summary["failures"]), 1)
        self.assertEqual(summary["failures"][0]["keyword"], "被騙")
        self.assertEqual(len(articles), 2)

    def test_dry_run_makes_no_network_requests(self):
        with patch.object(ptt_crawler, "crawl_ptt_multi") as multi:
            with patch.object(ptt_crawler, "_request_get") as req:
                with patch("sys.argv", [
                    "ptt_crawler",
                    "--boards",
                    "Bunco",
                    "e-shopping",
                    "--keywords",
                    "詐騙",
                    "被騙",
                    "--pages",
                    "10",
                    "--dry-run",
                ]):
                    ptt_crawler.main()
                req.assert_not_called()
                multi.assert_not_called()

    def test_chinese_csv_roundtrip_and_rag_compatible(self):
        articles = [
            _article(
                "https://www.ptt.cc/bbs/Bunco/M.1.A.1.html",
                "[心得] 我被騙了匯款",
                "Bunco",
                "詐騙、被騙",
                content="完整中文正文：對方要我匯款",
            )
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ptt_scam_cases.csv"
            ptt_crawler.save_articles_to_csv(articles, str(path))
            with open(path, "r", encoding="utf-8-sig") as file:
                rows = list(csv.DictReader(file))
            self.assertEqual(rows[0]["title"], "[心得] 我被騙了匯款")
            self.assertEqual(rows[0]["content"], "完整中文正文：對方要我匯款")
            self.assertEqual(rows[0]["source_board"], "Bunco")
            self.assertEqual(rows[0]["review_status"], "unreviewed")

            # rag_searcher 只依賴核心欄位，多欄位仍可讀
            with patch.object(rag_searcher, "PTT_CSV", str(path)), patch.object(
                rag_searcher, "DCARD_CSV", str(Path(tmp) / "missing.csv")
            ):
                hits = rag_searcher.search_related_cases("我遇到詐騙", top_k=2)
            self.assertTrue(len(hits) >= 1)
            self.assertIn("PTT", hits[0]["title"])
            self.assertTrue(hits[0]["content"])

    def test_possible_case_type_hints(self):
        self.assertEqual(
            ptt_crawler.guess_possible_case_type("[心得] x", "我被騙了"),
            "possible_personal_case",
        )
        self.assertEqual(
            ptt_crawler.guess_possible_case_type("[新聞] 防詐宣導", "警方提醒"),
            "possible_news_or_awareness",
        )
        self.assertEqual(
            ptt_crawler.guess_possible_case_type("[閒聊] 討論", "一般內容"),
            "unknown",
        )

    def test_duplicate_board_keyword_args_deduped(self):
        ns = MagicMock()
        ns.boards = ["Bunco", "Bunco"]
        ns.board = ["Bunco"]
        ns.keywords = ["詐騙", "被騙"]
        ns.keyword = ["詐騙"]
        boards, keywords = ptt_crawler.parse_boards_and_keywords(ns)
        self.assertEqual(boards, ["Bunco"])
        self.assertEqual(keywords, ["詐騙", "被騙"])


if __name__ == "__main__":
    unittest.main()
