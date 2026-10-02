"""
第一階段完整流程（研究用入口邏輯）。

重用既有模組，不複製 crawler / cross-reference 核心：
  1. crawlers.ptt_crawler（BOARDS / KEYWORDS / crawl_ptt_multi）
  2. scripts.ptt_dual_source_cross_reference.run_dual_source
  3. scripts.import_ptt_candidates_to_review（append merge）
  4. scripts.article1_status（exact_match / temp）

不自動 commit / push / 開 PR，不碰 answers.json 內容，不做 AI 抽詞。
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from crawlers.ptt_crawler import (
    BOARDS,
    DEFAULT_OUTPUT,
    KEYWORDS,
    REQUEST_DELAY_SEC,
    crawl_ptt_multi,
    save_articles_to_csv,
)
from scripts.article1_status import (
    ARTICLE1_STATUS_EXACT_MATCH,
    ARTICLE1_STATUS_TEMP,
)
from scripts.import_ptt_candidates_to_review import (
    DEFAULT_OUT_DIR,
    canonicalize_url,
    to_review_item,
    write_items,
)
from scripts.ptt_dual_source_cross_reference import run_dual_source

DEFAULT_CSV_176455 = "data/raw/NPA_WEBURL_20260930.csv"
DEFAULT_CSV_160055 = "data/raw/NPA_FAKE_INVEST_20260930.csv"
DEFAULT_XREF_OUTPUT_DIR = "data/review/run_stage1_pipeline"
DEFAULT_PAGES = 10


def load_article1_status_rows(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"找不到 Article 1 狀態檔：{path}")
    with open(path, encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def count_article1_statuses(rows: list[dict]) -> dict[str, int]:
    exact = 0
    temp = 0
    other = 0
    for row in rows:
        status = (row.get("status") or "").strip()
        if status == ARTICLE1_STATUS_EXACT_MATCH:
            exact += 1
        elif status == ARTICLE1_STATUS_TEMP:
            temp += 1
        else:
            other += 1
    return {
        "exact_match": exact,
        "temp": temp,
        "other": other,
        "total": len(rows),
    }


def select_temp_rows(rows: list[dict]) -> list[dict]:
    """只取 status=temp；exact_match 與其他狀態都不進 Temp Review 匯入。"""
    selected: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        status = (row.get("status") or "").strip()
        if status != ARTICLE1_STATUS_TEMP:
            continue
        url = (row.get("url") or "").strip()
        key = canonicalize_url(url)
        if not key or key in seen:
            continue
        seen.add(key)
        selected.append(row)
    return selected


def append_temp_rows_to_review(
    temp_rows: list[dict],
    *,
    out_dir: Path,
) -> dict:
    """
    將 temp 文章 append/merge 進 ptt_candidates/items.csv。

    - 保留既有 items
    - 同 URL 不重複、不覆寫既有列
    - 不刪除既有資料
    - 不修改 answers.json 內容（不存在時才建立空檔）
    """
    out_dir = Path(out_dir)
    items_path = out_dir / "items.csv"
    answers_path = out_dir / "answers.json"

    imported_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_items = [to_review_item(row, imported_at) for row in temp_rows]
    # to_review_item 固定寫 status=temp；此處再保險一次
    for item in new_items:
        item["status"] = ARTICLE1_STATUS_TEMP

    existing: list[dict] = []
    if items_path.exists():
        with open(items_path, encoding="utf-8-sig", newline="") as file:
            existing = list(csv.DictReader(file))

    by_key: dict[str, dict] = {}
    for row in existing:
        key = row.get("dedup_key") or canonicalize_url(row.get("article_url") or "")
        if key:
            by_key[key] = row

    added = 0
    skipped_existing = 0
    for item in new_items:
        key = item["dedup_key"]
        if not key:
            continue
        if key in by_key:
            skipped_existing += 1
            continue
        by_key[key] = item
        added += 1

    merged = list(by_key.values())
    merged.sort(key=lambda row: row.get("review_id") or "")
    write_items(items_path, merged)

    # 只確保 answers 檔存在；絕不覆寫既有標註
    if not answers_path.exists():
        answers_path.write_text("{}", encoding="utf-8")

    return {
        "items_path": str(items_path),
        "answers_path": str(answers_path),
        "temp_selected": len(new_items),
        "added": added,
        "skipped_existing": skipped_existing,
        "items_total": len(merged),
    }


def run_crawl_step(
    *,
    pages: int = DEFAULT_PAGES,
    output: str = DEFAULT_OUTPUT,
    delay_sec: float = REQUEST_DELAY_SEC,
    boards: list[str] | None = None,
    keywords: list[str] | None = None,
) -> dict:
    use_boards = list(boards) if boards is not None else list(BOARDS)
    use_keywords = list(keywords) if keywords is not None else list(KEYWORDS)
    articles, summary = crawl_ptt_multi(
        boards=use_boards,
        keywords=use_keywords,
        pages=pages,
        delay_sec=delay_sec,
    )
    if articles:
        save_articles_to_csv(articles, output)
    summary_path = (
        output.replace(".csv", "_summary.json")
        if output.endswith(".csv")
        else output + "_summary.json"
    )
    with open(summary_path, "w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)
    return {
        "output": output,
        "summary_path": summary_path,
        "article_count": len(articles),
        "boards": use_boards,
        "keywords": use_keywords,
        "pages": pages,
        "crawl_summary": summary,
    }


def run_stage1_pipeline(
    *,
    pages: int = DEFAULT_PAGES,
    ptt_csv: str = DEFAULT_OUTPUT,
    csv_176455: str = DEFAULT_CSV_176455,
    csv_160055: str = DEFAULT_CSV_160055,
    xref_output_dir: str = DEFAULT_XREF_OUTPUT_DIR,
    review_out_dir: str | Path = DEFAULT_OUT_DIR,
    delay_sec: float = REQUEST_DELAY_SEC,
    skip_crawl: bool = False,
    skip_xref: bool = False,
) -> dict:
    """
    執行第一階段完整流程，回傳摘要 dict。
    """
    result: dict = {
        "ptt_csv": ptt_csv,
        "xref_output_dir": xref_output_dir,
        "review_out_dir": str(review_out_dir),
    }

    if skip_crawl:
        path = Path(ptt_csv)
        if not path.exists():
            raise FileNotFoundError(f"skip_crawl 但找不到既有爬蟲 CSV：{ptt_csv}")
        with open(path, encoding="utf-8-sig", newline="") as file:
            crawl_count = sum(1 for _ in csv.DictReader(file))
        result["crawl"] = {
            "skipped": True,
            "output": ptt_csv,
            "article_count": crawl_count,
        }
    else:
        crawl_info = run_crawl_step(
            pages=pages,
            output=ptt_csv,
            delay_sec=delay_sec,
        )
        crawl_info["skipped"] = False
        result["crawl"] = crawl_info

    article1_path = Path(xref_output_dir) / "ptt_article1_status.csv"
    if skip_xref:
        if not article1_path.exists():
            raise FileNotFoundError(
                f"skip_xref 但找不到 Article 1 狀態檔：{article1_path}"
            )
        result["xref"] = {"skipped": True, "article1_status_csv": str(article1_path)}
    else:
        xref_stats = run_dual_source(
            ptt_csv,
            csv_176455,
            csv_160055,
            xref_output_dir,
        )
        result["xref"] = {
            "skipped": False,
            "stats": xref_stats,
            "article1_status_csv": str(article1_path),
        }

    article1_rows = load_article1_status_rows(article1_path)
    status_counts = count_article1_statuses(article1_rows)
    temp_rows = select_temp_rows(article1_rows)
    import_info = append_temp_rows_to_review(
        temp_rows,
        out_dir=Path(review_out_dir),
    )

    result["article1"] = status_counts
    result["import"] = import_info
    result["summary"] = {
        "爬蟲文章": result["crawl"].get("article_count", 0),
        "exact_match": status_counts["exact_match"],
        "temp": status_counts["temp"],
        "新增 Review": import_info["added"],
        "已存在／跳過": import_info["skipped_existing"],
        "Review 總筆數": import_info["items_total"],
    }
    return result


def print_pipeline_summary(result: dict) -> None:
    summary = result.get("summary") or {}
    print("==== 第一階段 Pipeline 摘要 ====")
    print(f"爬蟲文章：{summary.get('爬蟲文章', 0)}")
    print(f"exact_match：{summary.get('exact_match', 0)}")
    print(f"temp：{summary.get('temp', 0)}")
    print(f"新增 Review：{summary.get('新增 Review', 0)}")
    print(f"已存在／跳過：{summary.get('已存在／跳過', 0)}")
    print(f"Review 總筆數：{summary.get('Review 總筆數', 0)}")
    import_info = result.get("import") or {}
    if import_info.get("items_path"):
        print(f"items：{import_info['items_path']}")
    print("note: 未修改 answers.json；未自動 commit / push / 開 PR")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="第一階段完整流程：爬蟲 → 雙來源比對 → 只 append temp 進 Review"
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=DEFAULT_PAGES,
        help=f"每個看板×關鍵字頁數（預設 {DEFAULT_PAGES}）",
    )
    parser.add_argument("--ptt-csv", default=DEFAULT_OUTPUT, help="爬蟲輸出 CSV")
    parser.add_argument("--csv-176455", default=DEFAULT_CSV_176455)
    parser.add_argument("--csv-160055", default=DEFAULT_CSV_160055)
    parser.add_argument(
        "--xref-output-dir",
        default=DEFAULT_XREF_OUTPUT_DIR,
        help="雙來源比對輸出目錄（內含 ptt_article1_status.csv）",
    )
    parser.add_argument(
        "--review-out-dir",
        default=str(DEFAULT_OUT_DIR),
        help="Review dataset 目錄（預設 data/review/ptt_candidates）",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=REQUEST_DELAY_SEC,
        help="爬蟲每篇請求間隔秒數",
    )
    parser.add_argument(
        "--skip-crawl",
        action="store_true",
        help="略過爬蟲，直接使用既有 --ptt-csv（測試／重跑比對用）",
    )
    parser.add_argument(
        "--skip-xref",
        action="store_true",
        help="略過比對，直接使用 --xref-output-dir 內既有 ptt_article1_status.csv",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只列出將使用的設定，不執行爬蟲／比對／匯入",
    )
    return parser


def main(argv: list[str] | None = None) -> dict | None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.dry_run:
        print("==== 第一階段 Pipeline dry-run ====")
        print(f"boards: {BOARDS}")
        print(f"keywords: {KEYWORDS}")
        print(f"pages: {args.pages}")
        print(f"ptt_csv: {args.ptt_csv}")
        print(f"csv_176455: {args.csv_176455}")
        print(f"csv_160055: {args.csv_160055}")
        print(f"xref_output_dir: {args.xref_output_dir}")
        print(f"review_out_dir: {args.review_out_dir}")
        print(f"skip_crawl: {args.skip_crawl}")
        print(f"skip_xref: {args.skip_xref}")
        return None

    result = run_stage1_pipeline(
        pages=args.pages,
        ptt_csv=args.ptt_csv,
        csv_176455=args.csv_176455,
        csv_160055=args.csv_160055,
        xref_output_dir=args.xref_output_dir,
        review_out_dir=args.review_out_dir,
        delay_sec=args.delay,
        skip_crawl=args.skip_crawl,
        skip_xref=args.skip_xref,
    )
    print_pipeline_summary(result)
    return result


if __name__ == "__main__":
    main()
