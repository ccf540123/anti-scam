# crawlers/Dcard_crawler.py
"""
Dcard 反詐騙版爬蟲。

可獨立執行：
  python -m crawlers.Dcard_crawler --limit 30 --output dcard_scam_cases.csv

注意：
  Dcard 目前常被 Cloudflare 擋住（HTTP 403）。
  若無法可靠取得資料，會回傳空結果並說明原因，不會拋出例外中斷其他流程。
"""

from __future__ import annotations

import argparse
import csv
import logging
import time
from typing import Iterable

import cloudscraper

from crawlers.base import Article

logger = logging.getLogger(__name__)

DEFAULT_FORUM = "anti_fraud"
DEFAULT_OUTPUT = "dcard_scam_cases.csv"
DEFAULT_LIMIT = 30
REQUEST_DELAY_SEC = 0.5
CSV_FIELDS = ["title", "url", "content", "source", "published_at"]


class DcardFraudCrawler:
    def __init__(self, forum_name: str = DEFAULT_FORUM):
        self.forum_name = forum_name
        self.api_url = f"https://www.dcard.tw/service/api/v2/forums/{self.forum_name}/posts"
        self.scraper = cloudscraper.create_scraper(
            browser={
                "browser": "chrome",
                "platform": "windows",
                "desktop": True,
            }
        )
        self.last_error = ""

    def fetch(self, limit: int = DEFAULT_LIMIT, delay_sec: float = REQUEST_DELAY_SEC) -> list[Article]:
        """
        抓取看板最新文章列表。
        失敗時回傳 []，並把原因寫在 self.last_error。
        """
        articles: list[Article] = []
        seen_urls: set[str] = set()
        self.last_error = ""

        # Dcard API 單次 limit 通常有上限，保守一次最多 100
        page_limit = max(1, min(int(limit), 100))
        params = {
            "popular": "false",
            "limit": page_limit,
        }

        try:
            print(f"📡 [Dcard] 正在抓取看板 {self.forum_name}（limit={page_limit}）...")
            resp = self.scraper.get(self.api_url, params=params, timeout=20)

            if resp.status_code == 403:
                self.last_error = (
                    "HTTP 403：Dcard / Cloudflare 擋下 API 請求，"
                    "目前無法在不額外繞過反爬的情況下可靠取得資料。"
                )
                print(f"⚠️ [Dcard] {self.last_error}")
                return []

            if resp.status_code != 200:
                self.last_error = f"HTTP {resp.status_code}：無法取得 Dcard API 資料"
                print(f"⚠️ [Dcard] {self.last_error}")
                return []

            # Cloudflare 有時回 200 但是 HTML challenge
            content_type = (resp.headers.get("Content-Type") or "").lower()
            if "application/json" not in content_type:
                self.last_error = (
                    f"回應不是 JSON（Content-Type={content_type or 'unknown'}），"
                    "可能仍是 Cloudflare 挑戰頁。"
                )
                print(f"⚠️ [Dcard] {self.last_error}")
                return []

            items = resp.json()
            if not isinstance(items, list):
                self.last_error = "API 回傳格式不是列表"
                print(f"⚠️ [Dcard] {self.last_error}")
                return []

            print(f"📥 [Dcard] 列表取得 {len(items)} 筆，開始整理內容...")

            for item in items:
                title = (item.get("title") or "").strip()
                post_id = item.get("id")
                if not title or not post_id:
                    continue

                url = f"https://www.dcard.tw/f/{self.forum_name}/p/{post_id}"
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                # 列表多半只有 excerpt；若有 content 則保存完整內容（不做 500 字截斷）
                content = (item.get("content") or item.get("excerpt") or "").strip()
                published_at = item.get("createdAt") or ""

                # 若列表沒有完整正文，嘗試打單篇 API（失敗則保留 excerpt，不中斷）
                if not item.get("content"):
                    detail = self._fetch_post_detail(post_id)
                    time.sleep(delay_sec)
                    if detail:
                        content = (detail.get("content") or content).strip()
                        published_at = detail.get("createdAt") or published_at

                articles.append(
                    Article(
                        url=url,
                        title=title,
                        content=content,
                        published_at=published_at,
                        source="dcard",
                    )
                )

            if not articles:
                self.last_error = self.last_error or "API 成功但沒有可用文章"
            return articles

        except Exception as exc:
            self.last_error = f"非預期錯誤: {exc}"
            print(f"❌ [Dcard] {self.last_error}")
            return []

    def _fetch_post_detail(self, post_id) -> dict | None:
        detail_url = f"https://www.dcard.tw/service/api/v2/posts/{post_id}"
        try:
            resp = self.scraper.get(detail_url, timeout=20)
            if resp.status_code != 200:
                return None
            if "application/json" not in (resp.headers.get("Content-Type") or "").lower():
                return None
            data = resp.json()
            return data if isinstance(data, dict) else None
        except Exception:
            return None


def save_articles_to_csv(articles: Iterable[Article], output_path: str) -> None:
    with open(output_path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for art in articles:
            writer.writerow(
                {
                    "title": art.title,
                    "url": art.url,
                    "content": art.content,
                    "source": art.source,
                    "published_at": art.published_at,
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl Dcard anti-fraud forum posts")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="最多抓幾篇（預設 30）")
    parser.add_argument("--forum", default=DEFAULT_FORUM, help="看板名稱（預設 anti_fraud）")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="輸出 CSV 路徑")
    parser.add_argument(
        "--delay",
        type=float,
        default=REQUEST_DELAY_SEC,
        help="單篇詳情請求間隔秒數（預設 0.5）",
    )
    args = parser.parse_args()

    crawler = DcardFraudCrawler(forum_name=args.forum)
    articles = crawler.fetch(limit=args.limit, delay_sec=args.delay)

    if articles:
        save_articles_to_csv(articles, args.output)
        print("==== Dcard 爬蟲結果 ====")
        print(f"成功篇數: {len(articles)}")
        print(f"輸出檔案: {args.output}")
        print(f"欄位: {', '.join(CSV_FIELDS)}")
    else:
        print("==== Dcard 爬蟲結果 ====")
        print("成功篇數: 0")
        print(f"失敗原因: {crawler.last_error or '未知'}")
        print("未覆寫輸出檔（避免用空資料蓋掉舊 CSV）")


if __name__ == "__main__":
    main()
