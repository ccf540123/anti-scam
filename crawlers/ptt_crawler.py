# crawlers/ptt_crawler.py
"""
PTT 看板搜尋爬蟲（研究／RAG 案例資料）。

相容舊用法：
  python -m crawlers.ptt_crawler --pages 10 --keyword 詐騙 --output ptt_scam_cases.csv

多看板 × 多關鍵字：
  python run_ptt_crawl.py --boards Bunco e-shopping --keywords 詐騙 被騙 --pages 10
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import quote, urlparse, urlunparse

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
MAX_RETRIES = 3
RETRY_BACKOFF_SEC = 1.0

# RAG 既有欄位（順序固定；不可改名／刪除）
RAG_CSV_FIELDS = ["title", "url", "content", "source", "published_at"]
# 額外 metadata（DictReader 多欄位不影響 rag_searcher）
META_CSV_FIELDS = [
    "source_board",
    "search_keyword",
    "search_page",
    "crawl_time",
    "dedup_key",
    "review_status",
    "possible_case_type",
]
CSV_FIELDS = RAG_CSV_FIELDS + META_CSV_FIELDS

PERSONAL_HINTS = ["我被", "我遇到", "匯款", "報案", "對話"]
NEWS_HINTS = ["新聞", "警方提醒", "防詐宣導"]


def _request_get(url: str, timeout: int = 15) -> requests.Response:
    """帶有限次數重試的 GET。"""
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, headers=PTT_HEADERS, timeout=timeout)
            return response
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SEC * attempt)
    assert last_error is not None
    raise last_error


def canonicalize_url(url: str) -> str:
    """正規化文章 URL，作為主要去重鍵。"""
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    # 去掉 fragment；path 去尾端 /
    path = (parsed.path or "").rstrip("/")
    return urlunparse((parsed.scheme, parsed.netloc.lower(), path, "", "", ""))


def guess_possible_case_type(title: str, content: str) -> str:
    """簡單提示規則，非最終分類。"""
    text = f"{title or ''}\n{content or ''}"
    if any(token in text for token in PERSONAL_HINTS):
        return "possible_personal_case"
    if any(token in text for token in NEWS_HINTS):
        return "possible_news_or_awareness"
    # 標題標籤也常見
    if re.match(r"\[新聞\]", title or ""):
        return "possible_news_or_awareness"
    return "unknown"


def _parse_metaline(main) -> tuple[str, str]:
    """回傳 (published_at, author)。"""
    published_at = ""
    author = ""
    for metaline in main.select(".article-metaline"):
        tag = metaline.select_one(".article-meta-tag")
        value = metaline.select_one(".article-meta-value")
        if not tag or not value:
            continue
        name = tag.get_text(strip=True)
        text = value.get_text(strip=True)
        if name == "時間":
            published_at = text
        elif name == "作者":
            # 通常為 "id (暱稱)" → 取 id
            author = text.split()[0] if text else ""
    return published_at, author


def crawl_ptt_article(url: str) -> tuple[str, str, str]:
    """
    抓取單篇文章。
    回傳 (content, published_at, author)。失敗時 content 為空字串。
    不含推文。
    """
    try:
        response = _request_get(url, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        main = soup.select_one("#main-content")
        if not main:
            return "", "", ""

        published_at, author = _parse_metaline(main)

        for tag in main.select(".article-metaline, .article-metaline-right, .push"):
            tag.decompose()

        content = main.get_text("\n", strip=True)
        return content, published_at, author
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠️ 文章抓取失敗: {url} ({exc})")
        return "", "", ""


def build_dedup_key(
    url: str,
    board: str,
    title: str,
    author: str,
    published_at: str,
    content: str,
) -> str:
    """
    去重鍵優先順序：
      1. canonical URL
      2. 看板 + 標題 + 作者 + 日期
      3. 標題與正文正規化 hash
    """
    canon = canonicalize_url(url)
    if canon:
        return canon

    fallback = "|".join(
        [
            (board or "").strip().lower(),
            (title or "").strip().lower(),
            (author or "").strip().lower(),
            (published_at or "").strip().lower(),
        ]
    )
    if any([(board or "").strip(), (title or "").strip(), (author or "").strip()]):
        return "meta:" + fallback

    norm = re.sub(r"\s+", "", f"{title or ''}{content or ''}").lower()
    digest = hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]
    return f"hash:{digest}"


def crawl_ptt_search(
    board: str = DEFAULT_BOARD,
    keyword: str = DEFAULT_KEYWORD,
    pages: int = 1,
    delay_sec: float = REQUEST_DELAY_SEC,
) -> tuple[list[Article], dict]:
    """
    依搜尋結果分頁抓取文章。
    回傳 (去重後文章列表, 統計資訊)。
    單一看板 × 單一關鍵字。
    """
    articles: list[Article] = []
    seen_keys: set[str] = set()
    stats = {
        "board": board,
        "keyword": keyword,
        "pages_requested": pages,
        "pages_fetched": 0,
        "raw_listings": 0,
        "duplicate_skipped": 0,
        "fetch_success": 0,
        "fetch_failed": 0,
        "failed": False,
        "error": "",
    }

    encoded_keyword = quote(keyword)
    next_url = f"https://www.ptt.cc/bbs/{board}/search?q={encoded_keyword}"
    crawl_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for page_idx in range(1, pages + 1):
        print(f"📡 [PTT] {board} / {keyword} 第 {page_idx}/{pages} 頁：{next_url}")
        try:
            response = _request_get(next_url, timeout=15)
            if response.status_code != 200:
                msg = f"搜尋頁狀態碼 {response.status_code}"
                print(f"  ⚠️ {msg}，停止此組合後續分頁")
                stats["failed"] = True
                stats["error"] = msg
                break
            soup = BeautifulSoup(response.text, "html.parser")
            stats["pages_fetched"] += 1
        except Exception as exc:  # noqa: BLE001
            msg = f"搜尋頁請求失敗: {exc}"
            print(f"  ⚠️ {msg}")
            stats["failed"] = True
            stats["error"] = msg
            break

        entries = soup.select(".r-ent")
        if not entries:
            print("  ⚠️ 本頁沒有文章，停止此組合")
            break

        for entry in entries:
            title_tag = entry.select_one(".title a")
            if not title_tag:
                stats["fetch_failed"] += 1
                continue

            title = title_tag.get_text(strip=True)
            href = title_tag.get("href") or ""
            article_url = "https://www.ptt.cc" + href
            stats["raw_listings"] += 1

            content, published_at, author = crawl_ptt_article(article_url)
            time.sleep(delay_sec)

            dedup_key = build_dedup_key(
                article_url, board, title, author, published_at, content
            )
            if dedup_key in seen_keys:
                stats["duplicate_skipped"] += 1
                continue
            seen_keys.add(dedup_key)

            if title and content:
                articles.append(
                    Article(
                        url=article_url,
                        title=title,
                        content=content,
                        published_at=published_at,
                        source="ptt",
                        source_board=board,
                        search_keyword=keyword,
                        search_page=str(page_idx),
                        crawl_time=crawl_time,
                        dedup_key=dedup_key,
                        review_status="unreviewed",
                        possible_case_type=guess_possible_case_type(title, content),
                        author=author,
                    )
                )
                stats["fetch_success"] += 1
            else:
                stats["fetch_failed"] += 1

        prev_button = soup.select_one("a.btn.wide:-soup-contains('上頁')")
        if not prev_button or not prev_button.get("href"):
            print("  ℹ️ 沒有下一頁（上頁），結束此組合分頁")
            break
        next_url = "https://www.ptt.cc" + prev_button["href"]
        time.sleep(delay_sec)

    return articles, stats


def merge_articles_by_dedup(articles: Iterable[Article]) -> list[Article]:
    """
    跨看板／關鍵字去重：同一篇文章只留一筆。
    多關鍵字命中時，search_keyword 以「、」合併。
    """
    merged: dict[str, Article] = {}
    for article in articles:
        key = article.dedup_key or canonicalize_url(article.url) or article.url
        existing = merged.get(key)
        if existing is None:
            # 複製一份，避免後續改到原物件
            merged[key] = Article(
                url=article.url,
                title=article.title,
                content=article.content,
                published_at=article.published_at,
                source=article.source,
                source_board=article.source_board,
                search_keyword=article.search_keyword,
                search_page=article.search_page,
                crawl_time=article.crawl_time,
                dedup_key=key,
                review_status=article.review_status or "unreviewed",
                possible_case_type=article.possible_case_type or "unknown",
                author=article.author,
            )
            continue

        # 合併關鍵字
        old_kws = [k for k in existing.search_keyword.split("、") if k]
        new_kws = [k for k in article.search_keyword.split("、") if k]
        combined = []
        for keyword in old_kws + new_kws:
            if keyword not in combined:
                combined.append(keyword)
        existing.search_keyword = "、".join(combined)

        # 較早出現的 search_page 優先（數字較小）
        try:
            if int(article.search_page or "999") < int(existing.search_page or "999"):
                existing.search_page = article.search_page
        except ValueError:
            pass

        # board：若原本空白則補上
        if not existing.source_board and article.source_board:
            existing.source_board = article.source_board

    # 穩定排序
    rows = list(merged.values())
    rows.sort(key=lambda a: (a.source_board or "", a.title or "", a.url or ""))
    return rows


def crawl_ptt_multi(
    boards: list[str],
    keywords: list[str],
    pages: int = 10,
    delay_sec: float = REQUEST_DELAY_SEC,
) -> tuple[list[Article], dict]:
    """執行所有看板 × 關鍵字組合，並跨組合去重。"""
    unique_boards = list(dict.fromkeys([b.strip() for b in boards if b and b.strip()]))
    unique_keywords = list(
        dict.fromkeys([k.strip() for k in keywords if k and k.strip()])
    )
    combos = [(b, k) for b in unique_boards for k in unique_keywords]

    all_articles: list[Article] = []
    per_combo: list[dict] = []
    failures: list[dict] = []

    for board, keyword in combos:
        try:
            articles, stats = crawl_ptt_search(
                board=board,
                keyword=keyword,
                pages=pages,
                delay_sec=delay_sec,
            )
        except Exception as exc:  # noqa: BLE001
            stats = {
                "board": board,
                "keyword": keyword,
                "pages_requested": pages,
                "pages_fetched": 0,
                "raw_listings": 0,
                "duplicate_skipped": 0,
                "fetch_success": 0,
                "fetch_failed": 0,
                "failed": True,
                "error": str(exc),
            }
            articles = []
            print(f"  ❌ 組合失敗 {board} × {keyword}: {exc}")

        per_combo.append(
            {
                "board": board,
                "keyword": keyword,
                "raw_listings": stats.get("raw_listings", 0),
                "fetch_success": stats.get("fetch_success", 0),
                "pages_fetched": stats.get("pages_fetched", 0),
                "failed": bool(stats.get("failed")),
                "error": stats.get("error", ""),
            }
        )
        if stats.get("failed"):
            failures.append(
                {
                    "board": board,
                    "keyword": keyword,
                    "pages": pages,
                    "error": stats.get("error", ""),
                }
            )
        all_articles.extend(articles)

    before = len(all_articles)
    merged = merge_articles_by_dedup(all_articles)

    board_counts: dict[str, int] = {}
    type_counts = {
        "possible_personal_case": 0,
        "possible_news_or_awareness": 0,
        "unknown": 0,
    }
    for article in merged:
        board_counts[article.source_board] = board_counts.get(article.source_board, 0) + 1
        type_counts[article.possible_case_type] = (
            type_counts.get(article.possible_case_type, 0) + 1
        )

    summary = {
        "boards": unique_boards,
        "keywords": unique_keywords,
        "pages": pages,
        "combinations": [{"board": b, "keyword": k} for b, k in combos],
        "per_combo": per_combo,
        "total_before_dedup": before,
        "total_after_dedup": len(merged),
        "board_counts": board_counts,
        "possible_case_type_counts": type_counts,
        "failures": failures,
    }
    return merged, summary


def fetch_all_ptt_scam(
    pages: int = 1,
    board: str = DEFAULT_BOARD,
    keyword: str = DEFAULT_KEYWORD,
    delay_sec: float = REQUEST_DELAY_SEC,
) -> list[Article]:
    """供其他模組（如 rag_searcher）呼叫的簡化接口。"""
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
                    "source_board": art.source_board,
                    "search_keyword": art.search_keyword,
                    "search_page": art.search_page,
                    "crawl_time": art.crawl_time,
                    "dedup_key": art.dedup_key,
                    "review_status": art.review_status or "unreviewed",
                    "possible_case_type": art.possible_case_type or "unknown",
                }
            )


def parse_boards_and_keywords(args: argparse.Namespace) -> tuple[list[str], list[str]]:
    boards: list[str] = []
    keywords: list[str] = []

    if getattr(args, "boards", None):
        boards.extend(args.boards)
    if getattr(args, "board", None):
        boards.extend(args.board)

    if getattr(args, "keywords", None):
        keywords.extend(args.keywords)
    if getattr(args, "keyword", None):
        # 相容舊版：--keyword 可重複；若完全沒給則用預設
        keywords.extend(args.keyword)

    if not boards:
        boards = [DEFAULT_BOARD]
    if not keywords:
        keywords = [DEFAULT_KEYWORD]

    # 去重但保序
    boards = list(dict.fromkeys([b.strip() for b in boards if b and b.strip()]))
    keywords = list(dict.fromkeys([k.strip() for k in keywords if k and k.strip()]))
    return boards, keywords


def print_summary(summary: dict) -> None:
    print("==== PTT 爬蟲結果 ====")
    print(f"看板: {summary['boards']}")
    print(f"關鍵字: {summary['keywords']}")
    print(f"每組合頁數: {summary['pages']}")
    print("--- 各組合原始篇數（列表項）---")
    for row in summary["per_combo"]:
        status = "FAIL" if row["failed"] else "OK"
        print(
            f"  [{status}] {row['board']} × {row['keyword']}: "
            f"raw={row['raw_listings']}, success={row['fetch_success']}, "
            f"pages_fetched={row['pages_fetched']}"
        )
    print(f"去重前總數: {summary['total_before_dedup']}")
    print(f"去重後總數: {summary['total_after_dedup']}")
    print(f"各看板篇數: {summary['board_counts']}")
    types = summary["possible_case_type_counts"]
    print(f"可能個人案例: {types.get('possible_personal_case', 0)}")
    print(f"可能新聞／宣導: {types.get('possible_news_or_awareness', 0)}")
    print(f"unknown: {types.get('unknown', 0)}")
    if summary["failures"]:
        print("--- 失敗項目 ---")
        for fail in summary["failures"]:
            print(
                f"  {fail['board']} × {fail['keyword']} (pages={fail['pages']}): "
                f"{fail['error']}"
            )
    else:
        print("失敗項目: 無")


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl PTT scam-related posts")
    parser.add_argument(
        "--pages", type=int, default=10, help="每個看板×關鍵字要抓取的搜尋頁數（預設 10）"
    )
    parser.add_argument(
        "--board",
        action="append",
        default=None,
        help="看板名稱（可重複）；未指定時預設 Bunco",
    )
    parser.add_argument(
        "--boards",
        nargs="+",
        default=None,
        help="多個看板（空白分隔），例如 --boards Bunco e-shopping",
    )
    parser.add_argument(
        "--keyword",
        action="append",
        default=None,
        help="搜尋關鍵字（可重複）；未指定時預設 詐騙",
    )
    parser.add_argument(
        "--keywords",
        nargs="+",
        default=None,
        help="多個關鍵字（空白分隔）",
    )
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="輸出 CSV 路徑")
    parser.add_argument(
        "--delay",
        type=float,
        default=REQUEST_DELAY_SEC,
        help="每篇文章請求間隔秒數（預設 0.5）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只列出即將執行的看板、關鍵字與頁數，不發送網路請求",
    )
    parser.add_argument(
        "--summary-json",
        default="",
        help="可選：寫入摘要 JSON 路徑（預設 <output>_summary.json）",
    )
    args = parser.parse_args()

    boards, keywords = parse_boards_and_keywords(args)
    combos = [(b, k) for b in boards for k in keywords]

    if args.dry_run:
        print("==== PTT dry-run（不發送網路請求）====")
        print(f"pages: {args.pages}")
        print(f"boards: {boards}")
        print(f"keywords: {keywords}")
        print(f"combinations ({len(combos)}):")
        for board, keyword in combos:
            print(f"  - {board} × {keyword}")
        print(f"output: {args.output}")
        return

    articles, summary = crawl_ptt_multi(
        boards=boards,
        keywords=keywords,
        pages=args.pages,
        delay_sec=args.delay,
    )
    print_summary(summary)

    summary_path = args.summary_json or (
        args.output.replace(".csv", "_summary.json")
        if args.output.endswith(".csv")
        else args.output + "_summary.json"
    )
    with open(summary_path, "w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)
    print(f"摘要: {summary_path}")

    if articles:
        save_articles_to_csv(articles, args.output)
        print(f"輸出檔案: {args.output}")
        print(f"欄位: {', '.join(CSV_FIELDS)}")
        print(f"RAG 核心欄位（相容）: {', '.join(RAG_CSV_FIELDS)}")
    else:
        print("未寫入輸出檔（成功篇數為 0，避免覆蓋既有 CSV）")
        if all(row.get("failed") for row in summary["per_combo"]):
            print("可能原因：PTT / Cloudflare 擋住請求（例如 HTTP 403）")


if __name__ == "__main__":
    if __package__ is None:
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from crawlers.ptt_crawler import main as _main

        _main()
    else:
        main()
