"""
第二階段：用新聞／宣導抽出的 keyword 重爬 PTT，找出較像「自己遇到詐騙」的候選案例。

流程：
  1. 讀取 keyword JSON（或先從 ptt_scam_cases.csv 抽出）
  2. 對每個 keyword 呼叫既有 Bunco 搜尋爬蟲（不合併成單一黑名單式 query）
  3. 依標題標籤 + 第一人稱／案例用語 vs 新聞用語打分
  4. 輸出全部命中與「Likely personal case」子集

不覆蓋 ptt_scam_cases.csv；不修改 Website / app.py。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from crawlers.ptt_crawler import DEFAULT_BOARD, crawl_ptt_search
from scripts.extract_scam_keywords_from_ptt import extract_keywords_from_ptt_csv

CASE_HINT_TAGS = {"心得", "問題", "閒聊", "求助", "分享", "情報", "經驗"}
NEWS_PSA_TAGS = {"新聞", "資訊", "公告"}

# 較像「自己遇到／正在求助」的用語
CASE_MARKERS = [
    r"我被騙",
    r"被騙了",
    r"我被詐",
    r"遭騙",
    r"受騙",
    r"求助",
    r"求救",
    r"不小心",
    r"對方要我",
    r"對方叫我",
    r"他要我",
    r"她要我",
    r"加了?\s*LINE",
    r"加LINE",
    r"匯了",
    r"已經匯",
    r"轉了",
    r"被要求",
    r"我匯款",
    r"我轉帳",
    r"點了連結",
    r"下載了",
    r"被盜",
    r"帳戶被",
    r"錢沒了",
    r"損失",
    r"請問這樣",
    r"有人遇過",
    r"大家小心",
    r"差點被騙",
    r"差點上當",
]

# 較像新聞／宣導轉貼
NEWS_MARKERS = [
    r"記者",
    r"報導",
    r"中央社",
    r"綜合報導",
    r"新聞稿",
    r"警政署",
    r"刑事局",
    r"165",
    r"民眾千萬",
    r"呼籲民眾",
    r"根據.{0,8}統計",
    r"撰文",
    r"原文網址",
    r"自由時報",
    r"聯合報",
    r"中時",
    r"公視",
    r"今日新聞",
    r"ETtoday",
]


@dataclass
class CaseCandidate:
    title: str
    url: str
    content: str
    published_at: str
    source: str
    matched_keyword: str
    title_tag: str
    case_score: int
    news_score: int
    case_label: str
    case_reasons: str


def title_tag(title: str) -> str:
    match = re.match(r"\[([^\]]+)\]", title or "")
    return match.group(1) if match else ""


def score_case_likelihood(title: str, content: str) -> tuple[int, int, str, str]:
    """
    回傳 (case_score, news_score, label, reasons)
    label: likely_personal_case | likely_news_or_psa | uncertain
    """
    tag = title_tag(title)
    text = f"{title}\n{content or ''}"
    reasons: list[str] = []

    case_score = 0
    news_score = 0

    if tag in CASE_HINT_TAGS:
        case_score += 3
        reasons.append(f"title_tag={tag}")
    if tag in NEWS_PSA_TAGS:
        news_score += 3
        reasons.append(f"title_tag={tag}")

    for pattern in CASE_MARKERS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            case_score += 2
            reasons.append(f"case_marker:{pattern}")
            break  # 避免同一類重複暴衝；至少記到有第一人稱跡象

    # 多算一點其他案例徵兆（不 break）
    extra_case = 0
    for pattern in CASE_MARKERS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            extra_case += 1
    if extra_case >= 2:
        case_score += min(extra_case - 1, 3)
        reasons.append(f"case_marker_count={extra_case}")

    news_hits = 0
    for pattern in NEWS_MARKERS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            news_hits += 1
    if news_hits:
        news_score += min(news_hits, 4)
        reasons.append(f"news_marker_count={news_hits}")

    # 標題含「詐騙」且是新聞板常見寫法
    if tag == "新聞":
        news_score += 1

    if case_score >= 4 and case_score > news_score:
        label = "likely_personal_case"
    elif news_score >= 3 and news_score >= case_score:
        label = "likely_news_or_psa"
    else:
        label = "uncertain"

    return case_score, news_score, label, "; ".join(reasons)


def load_keywords(path: str | None, ptt_csv: str) -> tuple[list[str], dict]:
    if path:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return list(payload.get("crawl_keywords") or []), payload
    payload = extract_keywords_from_ptt_csv(ptt_csv)
    return list(payload["crawl_keywords"]), payload


OUTPUT_FIELDS = [
    "title",
    "url",
    "content",
    "published_at",
    "source",
    "matched_keyword",
    "title_tag",
    "case_score",
    "news_score",
    "case_label",
    "case_reasons",
]


def write_candidates(path: Path, rows: list[CaseCandidate]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def run_case_recrawl(
    keywords: list[str],
    board: str = DEFAULT_BOARD,
    pages_per_keyword: int = 3,
    delay_sec: float = 0.5,
    max_keywords: int | None = None,
) -> tuple[list[CaseCandidate], dict]:
    used_keywords = keywords[:max_keywords] if max_keywords else keywords
    by_url: dict[str, CaseCandidate] = {}
    stats = {
        "keywords": used_keywords,
        "pages_per_keyword": pages_per_keyword,
        "board": board,
        "raw_fetched_articles": 0,
        "unique_articles": 0,
        "label_counts": {},
        "per_keyword_fetched": {},
        "errors": [],
    }

    for keyword in used_keywords:
        print(f"\n==== keyword: {keyword} ====")
        try:
            articles, crawl_stats = crawl_ptt_search(
                board=board,
                keyword=keyword,
                pages=pages_per_keyword,
                delay_sec=delay_sec,
            )
        except Exception as exc:  # noqa: BLE001
            stats["errors"].append({"keyword": keyword, "error": str(exc)})
            print(f"  keyword failed: {exc}")
            continue

        stats["per_keyword_fetched"][keyword] = {
            "fetch_success": crawl_stats.get("fetch_success", 0),
            "pages_fetched": crawl_stats.get("pages_fetched", 0),
            "raw_listings": crawl_stats.get("raw_listings", 0),
        }
        stats["raw_fetched_articles"] += len(articles)

        for article in articles:
            case_score, news_score, label, reasons = score_case_likelihood(
                article.title, article.content
            )
            candidate = CaseCandidate(
                title=article.title,
                url=article.url,
                content=article.content,
                published_at=article.published_at,
                source=article.source,
                matched_keyword=keyword,
                title_tag=title_tag(article.title),
                case_score=case_score,
                news_score=news_score,
                case_label=label,
                case_reasons=reasons,
            )
            existing = by_url.get(article.url)
            if existing is None:
                by_url[article.url] = candidate
            else:
                # 同一篇被多個 keyword 命中：保留較高 case_score，並記錄 keyword
                if keyword not in existing.matched_keyword.split("|"):
                    existing.matched_keyword = existing.matched_keyword + "|" + keyword
                if candidate.case_score > existing.case_score:
                    existing.case_score = candidate.case_score
                    existing.news_score = candidate.news_score
                    existing.case_label = candidate.case_label
                    existing.case_reasons = candidate.case_reasons

        time.sleep(delay_sec)

    rows = list(by_url.values())
    stats["unique_articles"] = len(rows)
    label_counts: dict[str, int] = {}
    for row in rows:
        label_counts[row.case_label] = label_counts.get(row.case_label, 0) + 1
    stats["label_counts"] = label_counts
    return rows, stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-crawl PTT with news-derived keywords for personal scam cases"
    )
    parser.add_argument("--ptt", default="ptt_scam_cases.csv", help="用來抽 keyword 的來源 CSV")
    parser.add_argument("--keywords-json", default="", help="已抽出的 keyword JSON；空白則現場抽取")
    parser.add_argument("--board", default=DEFAULT_BOARD)
    parser.add_argument("--pages-per-keyword", type=int, default=3)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument(
        "--max-keywords",
        type=int,
        default=0,
        help="只跑前 N 個 keyword（0=全部）；本機測試可先用 5",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="預設 data/review/run_YYYYMMDD_case_recrawl",
    )
    args = parser.parse_args()

    keywords, keyword_payload = load_keywords(args.keywords_json or None, args.ptt)
    max_keywords = args.max_keywords or None

    day = date.today().strftime("%Y%m%d")
    out_dir = Path(args.output_dir or f"data/review/run_{day}_case_recrawl")
    out_dir.mkdir(parents=True, exist_ok=True)

    # 若現場抽取，也存一份 keyword 快照
    kw_path = Path(f"data/raw/scam_keywords_from_news_{day}.json")
    kw_path.parent.mkdir(parents=True, exist_ok=True)
    if not args.keywords_json:
        kw_path.write_text(
            json.dumps(keyword_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    else:
        # 仍複製／寫入本次使用清單，方便報告
        used_payload = {
            "source_keywords_json": args.keywords_json,
            "crawl_keywords": keywords[:max_keywords] if max_keywords else keywords,
            "extracted_on": day,
        }
        kw_path.write_text(
            json.dumps(used_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    rows, stats = run_case_recrawl(
        keywords=keywords,
        board=args.board,
        pages_per_keyword=args.pages_per_keyword,
        delay_sec=args.delay,
        max_keywords=max_keywords,
    )

    all_path = out_dir / "ptt_keyword_hits_all.csv"
    case_path = out_dir / "ptt_likely_personal_cases.csv"
    uncertain_path = out_dir / "ptt_uncertain_cases.csv"

    cases = [r for r in rows if r.case_label == "likely_personal_case"]
    uncertain = [r for r in rows if r.case_label == "uncertain"]

    write_candidates(all_path, rows)
    write_candidates(case_path, cases)
    write_candidates(uncertain_path, uncertain)

    summary = {
        **stats,
        "keyword_file": str(kw_path),
        "output_dir": str(out_dir),
        "likely_personal_case_count": len(cases),
        "uncertain_count": len(uncertain),
        "likely_news_or_psa_count": stats.get("label_counts", {}).get(
            "likely_news_or_psa", 0
        ),
        "output_files": [str(all_path), str(case_path), str(uncertain_path)],
        "method_notes": {
            "step1": "Extract scam-method keywords from news/PSA-heavy Bunco posts",
            "step2": "Search Bunco again with each keyword (separate queries)",
            "step3": "Score personal-case likelihood; do NOT auto-label scam/non-scam",
            "keeps_original_csv": True,
        },
    }
    summary_path = out_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n==== Case re-crawl summary ====")
    print(f"keywords used: {len(stats['keywords'])}")
    print(f"unique articles: {stats['unique_articles']}")
    print(f"label_counts: {stats['label_counts']}")
    print(f"likely_personal_case: {len(cases)}")
    print(f"output_dir: {out_dir}")
    if stats["errors"]:
        print(f"errors: {stats['errors']}")
    if stats["unique_articles"] == 0 and stats.get("raw_fetched_articles", 0) == 0:
        print(
            "WARNING: 0 articles fetched. If this is Cloud/CI, PTT may block (403). "
            "Run on your Mac: python run_ptt_case_recrawl.py --pages-per-keyword 3"
        )


if __name__ == "__main__":
    main()
