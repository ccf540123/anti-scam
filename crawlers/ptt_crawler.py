# crawlers/ptt_crawler.py
"""
PTT Bunco 板「詐騙」搜尋爬蟲。

可獨立執行：
  python -m crawlers.ptt_crawler --pages 10 --keyword 詐騙 --output ptt_scam_cases.csv
"""

from __future__ import annotations

import argparse
import csv
import time
from typing import Iterable
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from crawlers.base import Article

PTT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; anti-scam-research/1.0)",
    "Cookie": "over18=1",
}
DEFAULT_BOARD = "Bunco"
DEFAULT_KEYWORD = "詐騙"
DEFAULT_OUTPUT = "ptt_scam_cases.csv"
REQUEST_DELAY_SEC = 0.5
CSV_FIELDS = ["title", "url", "content", "source", "published_at"]


def _parse_published_at(main) -> str:
    """從文章 metaline 解析「時間」欄位。"""
    for metaline in main.select(".article-metaline"):
        tag = metaline.select_one(".article-meta-tag")
        value = metaline.select_one(".article-meta-value")
        if tag and value and tag.get_text(strip=True) == "時間":
            return value.get_text(strip=True)
    return ""


def crawl_ptt_article(url: str) -> tuple[str, str]:
    """
    抓取單篇文章。
    回傳 (content, published_at)。失敗時 content 為空字串。
    不含推文。
    """
    try:
        response = requests.get(url, headers=PTT_HEADERS, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        main = soup.select_one("#main-content")
        if not main:
            return "", ""

        published_at = _parse_published_at(main)

        # 先拿時間，再移除 metaline / 推文，避免混進正文
        for tag in main.select(".article-metaline, .article-metaline-right, .push"):
            tag.decompose()

        content = main.get_text("\n", strip=True)
        return content, published_at
    except Exception as exc:
        print(f"  ⚠️ 文章抓取失敗: {url} ({exc})")
        return "", ""


def crawl_ptt_search(
    board: str = DEFAULT_BOARD,
    keyword: str = DEFAULT_KEYWORD,
    pages: int = 1,
    delay_sec: float = REQUEST_DELAY_SEC,
) -> tuple[list[Article], dict]:
    """
    依搜尋結果分頁抓取文章。
    回傳 (去重後文章列表, 統計資訊)。
    """
    articles: list[Article] = []
    seen_urls: set[str] = set()
    stats = {
        "pages_requested": pages,
        "pages_fetched": 0,
        "raw_listings": 0,
        "duplicate_skipped": 0,
        "fetch_success": 0,
        "fetch_failed": 0,
    }

    encoded_keyword = quote(keyword)
    next_url = f"https://www.ptt.cc/bbs/{board}/search?q={encoded_keyword}"

    for page_idx in range(1, pages + 1):
        print(f"📡 [PTT] 第 {page_idx}/{pages} 頁：{next_url}")
        try:
            response = requests.get(next_url, headers=PTT_HEADERS, timeout=15)
            if response.status_code != 200:
                print(f"  ⚠️ 搜尋頁狀態碼 {response.status_code}，停止後續分頁")
                break
            soup = BeautifulSoup(response.text, "html.parser")
            stats["pages_fetched"] += 1
        except Exception as exc:
            print(f"  ⚠️ 搜尋頁請求失敗: {exc}")
            break

        entries = soup.select(".r-ent")
        if not entries:
            print("  ⚠️ 本頁沒有文章，停止")
            break

        for entry in entries:
            title_tag = entry.select_one(".title a")
            if not title_tag:
                # 文章可能已刪除
                stats["fetch_failed"] += 1
                continue

            title = title_tag.get_text(strip=True)
            href = title_tag.get("href") or ""
            article_url = "https://www.ptt.cc" + href
            stats["raw_listings"] += 1

            if article_url in seen_urls:
                stats["duplicate_skipped"] += 1
                continue
            seen_urls.add(article_url)

            content, published_at = crawl_ptt_article(article_url)
            time.sleep(delay_sec)

            if title and content:
                articles.append(
                    Article(
                        url=article_url,
                        title=title,
                        content=content,
                        published_at=published_at,
                        source="ptt",
                    )
                )
                stats["fetch_success"] += 1
            else:
                stats["fetch_failed"] += 1

        prev_button = soup.select_one("a.btn.wide:-soup-contains('上頁')")
        if not prev_button or not prev_button.get("href"):
            print("  ℹ️ 沒有下一頁（上頁），結束分頁")
            break
        next_url = "https://www.ptt.cc" + prev_button["href"]
        time.sleep(delay_sec)

    return articles, stats


def fetch_all_ptt_scam(
    pages: int = 1,
    board: str = DEFAULT_BOARD,
    keyword: str = DEFAULT_KEYWORD,
    delay_sec: float = REQUEST_DELAY_SEC,
) -> list[Article]:
    """供其他模組呼叫的簡化接口。"""
    print(f"📡 正在爬取 PTT: {board} / {keyword} / pages={pages}")
    articles, stats = crawl_ptt_search(
        board=board,
        keyword=keyword,
        pages=pages,
        delay_sec=delay_sec,
    )
    print(
        f"✅ PTT 完成：成功 {stats['fetch_success']} 篇，"
        f"失敗 {stats['fetch_failed']} 篇，"
        f"去重略過 {stats['duplicate_skipped']} 篇"
    )
    return articles


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
    parser = argparse.ArgumentParser(description="Crawl PTT scam-related posts")
    parser.add_argument("--pages", type=int, default=10, help="要抓取的搜尋頁數（預設 10）")
    parser.add_argument("--board", default=DEFAULT_BOARD, help="看板名稱（預設 Bunco）")
    parser.add_argument("--keyword", default=DEFAULT_KEYWORD, help="搜尋關鍵字（預設 詐騙）")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="輸出 CSV 路徑")
    parser.add_argument(
        "--delay",
        type=float,
        default=REQUEST_DELAY_SEC,
        help="每篇文章請求間隔秒數（預設 0.5）",
    )
    args = parser.parse_args()

    articles, stats = crawl_ptt_search(
        board=args.board,
        keyword=args.keyword,
        pages=args.pages,
        delay_sec=args.delay,
    )

    print("==== PTT 爬蟲結果 ====")
    print(f"看板 / 關鍵字: {args.board} / {args.keyword}")
    print(f"請求頁數: {stats['pages_requested']}")
    print(f"實際抓到的搜尋頁: {stats['pages_fetched']}")
    print(f"搜尋列表原始篇數: {stats['raw_listings']}")
    print(f"URL 去重略過: {stats['duplicate_skipped']}")
    print(f"成功取得完整正文: {stats['fetch_success']}")
    print(f"失敗（刪文/空正文/請求失敗）: {stats['fetch_failed']}")
    print(f"去重後文章數: {len(articles)}")

    if articles:
        save_articles_to_csv(articles, args.output)
        print(f"輸出檔案: {args.output}")
        print(f"欄位: {', '.join(CSV_FIELDS)}")
    else:
        print("未寫入輸出檔（成功篇數為 0，避免覆蓋既有 CSV）")
        if stats["pages_fetched"] == 0:
            print("可能原因：PTT / Cloudflare 擋住請求（例如 HTTP 403）")


if __name__ == "__main__":
    main()
