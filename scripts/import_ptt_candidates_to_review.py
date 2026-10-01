"""
從 ptt_scam_cases.csv 匯入「候選文章」到獨立 Review dataset。

- 不修改、不覆蓋原始 ptt_scam_cases.csv
- 不自動匯入全部：必須明確指定篩選條件或 --all
- 輸出到 data/review/ptt_candidates/（與既有 Fuzzy review 分開）

用法範例：
  python run_import_ptt_review.py --limit 20
  python run_import_ptt_review.py --boards Bunco --keywords 被騙 --limit 50
  python run_import_ptt_review.py --urls-file urls.txt
  python run_import_ptt_review.py --all
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

DEFAULT_SOURCE = "ptt_scam_cases.csv"
DEFAULT_OUT_DIR = Path("data/review/ptt_candidates")

ITEM_FIELDS = [
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
]


def canonicalize_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    path = (parsed.path or "").rstrip("/")
    return urlunparse((parsed.scheme, parsed.netloc.lower(), path, "", "", ""))


def stable_review_id(url: str) -> str:
    key = canonicalize_url(url) or url.strip()
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    return f"ptt_{digest}"


def load_source_rows(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"找不到來源 CSV：{path}")
    with open(path, encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def filter_rows(
    rows: list[dict],
    *,
    boards: list[str] | None,
    keywords: list[str] | None,
    urls: set[str] | None,
    limit: int | None,
) -> list[dict]:
    board_set = {b.strip().lower() for b in (boards or []) if b.strip()}
    keyword_set = {k.strip() for k in (keywords or []) if k.strip()}
    url_set = {canonicalize_url(u) for u in (urls or set()) if u.strip()}
    url_set.discard("")

    selected: list[dict] = []
    seen: set[str] = set()

    for row in rows:
        url = (row.get("url") or "").strip()
        canon = canonicalize_url(url)
        if not canon:
            continue
        if canon in seen:
            continue

        board = (row.get("source_board") or "").strip()
        keyword = (row.get("search_keyword") or "").strip()

        if board_set and board.lower() not in board_set:
            continue
        if keyword_set:
            parts = [p.strip() for p in re.split(r"[、,|/]+", keyword) if p.strip()]
            if not parts:
                # 舊 CSV 可能沒有 search_keyword：允許用標題含關鍵字作備援？
                # 為避免默默匯入錯誤資料，沒有 keyword 欄位時僅在使用者未指定 --keywords 才收。
                continue
            if not any(k in parts or k in keyword for k in keyword_set):
                continue
        if url_set and canon not in url_set:
            continue

        seen.add(canon)
        selected.append(row)
        if limit is not None and len(selected) >= limit:
            break

    return selected


def to_review_item(row: dict, imported_at: str) -> dict:
    url = (row.get("url") or "").strip()
    return {
        "review_id": stable_review_id(url),
        "dataset_type": "ptt_candidate",
        "dedup_key": canonicalize_url(url),
        "title": row.get("title") or "",
        "article_url": url,
        "content": row.get("content") or "",
        "published_at": row.get("published_at") or "",
        "source": row.get("source") or "ptt",
        "source_board": row.get("source_board") or "",
        "search_keyword": row.get("search_keyword") or "",
        "imported_at": imported_at,
        "review_status": "pending",
        "status": "temp",  # Article 1：等待人工；不是 non_match / 最終案例
        "article_type": "",
        "human_notes": "",
        "reviewer": "",
    }


def write_items(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=ITEM_FIELDS)
        writer.writeheader()
        for item in items:
            writer.writerow(item)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import selected PTT crawl rows into an independent review dataset"
    )
    parser.add_argument("--source", default=DEFAULT_SOURCE, help="來源 CSV（預設 ptt_scam_cases.csv）")
    parser.add_argument(
        "--out-dir",
        default=str(DEFAULT_OUT_DIR),
        help="Review dataset 目錄（預設 data/review/ptt_candidates）",
    )
    parser.add_argument("--boards", nargs="+", default=None, help="只匯入這些看板")
    parser.add_argument("--keywords", nargs="+", default=None, help="只匯入含這些搜尋關鍵字的列")
    parser.add_argument("--urls-file", default="", help="只匯入檔案中列出的文章 URL（一行一個）")
    parser.add_argument("--limit", type=int, default=None, help="最多匯入幾篇")
    parser.add_argument(
        "--all",
        action="store_true",
        help="明確允許匯入來源檔全部列（仍可搭配 --limit）",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="與既有 ptt_candidates/items.csv 合併（同 URL 不重複）",
    )
    args = parser.parse_args()

    if not args.all and not args.boards and not args.keywords and not args.urls_file and args.limit is None:
        parser.error(
            "為避免一次匯入全部，請至少指定 --limit / --boards / --keywords / --urls-file，"
            "或明確加上 --all"
        )

    urls: set[str] = set()
    if args.urls_file:
        text = Path(args.urls_file).read_text(encoding="utf-8")
        urls = {line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")}

    source_rows = load_source_rows(Path(args.source))
    selected = filter_rows(
        source_rows,
        boards=args.boards,
        keywords=args.keywords,
        urls=urls or None,
        limit=args.limit,
    )

    imported_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_items = [to_review_item(row, imported_at) for row in selected]

    out_dir = Path(args.out_dir)
    items_path = out_dir / "items.csv"

    if args.append and items_path.exists():
        with open(items_path, encoding="utf-8-sig", newline="") as existing_file:
            existing = list(csv.DictReader(existing_file))
        by_key = {
            (row.get("dedup_key") or canonicalize_url(row.get("article_url") or "")): row
            for row in existing
        }
        for item in new_items:
            key = item["dedup_key"]
            if key and key not in by_key:
                by_key[key] = item
        merged = list(by_key.values())
        merged.sort(key=lambda r: r.get("review_id") or "")
        write_items(items_path, merged)
        final_count = len(merged)
    else:
        write_items(items_path, new_items)
        final_count = len(new_items)

    # 確保 answers 檔存在但不清掉既有標註
    answers_path = out_dir / "answers.json"
    if not answers_path.exists():
        answers_path.write_text("{}", encoding="utf-8")

    print("==== Import PTT → Review ====")
    print(f"source: {args.source} ({len(source_rows)} rows)")
    print(f"selected: {len(selected)}")
    print(f"output items: {items_path} ({final_count} rows)")
    print(f"answers file: {answers_path}")
    print("note: original ptt_scam_cases.csv was NOT modified")
    print("open /review and choose dataset「PTT 候選文章」to annotate")


if __name__ == "__main__":
    main()
