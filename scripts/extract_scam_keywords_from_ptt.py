"""
從現有 PTT 新聞／宣導文抽出「詐騙手法相關 keyword」，供第二階段重爬使用。

來源預設：ptt_scam_cases.csv（目前多為 [新聞]/[資訊]）
輸出：data/raw/scam_keywords_from_news_<date>.json

不修改 Website / app.py。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

# 研究用手法詞庫：用來在新聞／宣導正文中計次，再挑出高頻詞當重爬 keyword
SEED_PATTERNS = [
    "假投資",
    "投資詐騙",
    "假交友",
    "交友詐騙",
    "假貸款",
    "貸款詐騙",
    "假中獎",
    "中獎詐騙",
    "假檢警",
    "假客服",
    "假房東",
    "租屋詐騙",
    "假求職",
    "求職詐騙",
    "網購詐騙",
    "拍賣詐騙",
    "遊戲詐騙",
    "一頁式",
    "人頭戶",
    "提款卡",
    "驗證碼",
    "OTP",
    "辦門號",
    "美化信用",
    "虛擬貨幣",
    "加密貨幣",
    "USDT",
    "比特幣",
    "博弈",
    "娛樂城",
    "釣魚",
    "換臉",
    "deepfake",
    "視訊換臉",
    "面交",
    "超商代碼",
    "詐騙包裹",
    "假退稅",
    "發票中獎",
    "健保卡",
    "LINE",
    "加好友",
    "匯款",
    "轉帳",
]

# 太泛、容易刷到無關文的詞：可計次但不當預設重爬 keyword
TOO_GENERIC = {
    "AI",
    "廣告",
    "投資",
    "獲利",
    "LINE",
    "臉書",
    "Facebook",
    "Meta",
    "匯款",
    "轉帳",
    "面交",
}

NEWS_OR_PSA_TAGS = {"新聞", "資訊"}


def title_tag(title: str) -> str:
    match = re.match(r"\[([^\]]+)\]", title or "")
    return match.group(1) if match else ""


def is_clean_method_keyword(phrase: str) -> bool:
    """排除新聞標題切出來的碎片（如『的詐騙』『萬詐騙』）。"""
    if not phrase or len(phrase) < 2 or len(phrase) > 8:
        return False
    if phrase in TOO_GENERIC:
        return False
    # 不要以虛字／量詞開頭的碎片
    if phrase[0] in "的了在是與及和被遭有又也把從對":
        return False
    if phrase in {"詐騙", "小心詐騙", "注意詐騙", "反詐騙", "防詐騙", "疑似詐騙"}:
        return False
    if phrase.endswith("詐騙") and len(phrase) <= 6:
        return True
    if phrase.startswith("假") and 2 <= len(phrase) <= 5:
        return True
    return phrase in {
        "一頁式",
        "人頭戶",
        "提款卡",
        "驗證碼",
        "OTP",
        "辦門號",
        "美化信用",
        "虛擬貨幣",
        "加密貨幣",
        "USDT",
        "比特幣",
        "博弈",
        "娛樂城",
        "釣魚",
        "換臉",
        "deepfake",
        "視訊換臉",
        "超商代碼",
        "詐騙包裹",
        "發票中獎",
    }


def extract_title_scam_phrases(title: str) -> list[str]:
    """從標題抓『XX詐騙』『假XX』（只供觀察，預設不直接當搜尋詞）。"""
    text = re.sub(r"^\[[^\]]+\]\s*", "", title or "")
    found: list[str] = []
    for match in re.findall(r"假[\u4e00-\u9fff]{1,4}", text):
        if is_clean_method_keyword(match):
            found.append(match)
    for match in re.findall(r"[\u4e00-\u9fff]{2,4}詐騙", text):
        if is_clean_method_keyword(match):
            found.append(match)
    return found


def extract_keywords_from_ptt_csv(
    ptt_csv: str,
    min_docs: int = 3,
    only_news_info: bool = True,
) -> dict:
    rows = list(csv.DictReader(open(ptt_csv, encoding="utf-8-sig")))
    pattern_docs = Counter()
    title_phrase_docs = Counter()
    used_rows = 0

    for row in rows:
        tag = title_tag(row.get("title") or "")
        if only_news_info and tag and tag not in NEWS_OR_PSA_TAGS:
            continue
        used_rows += 1
        text = f"{row.get('title') or ''}\n{row.get('content') or ''}"
        for pattern in SEED_PATTERNS:
            if re.search(re.escape(pattern), text, flags=re.IGNORECASE):
                pattern_docs[pattern] += 1
        for phrase in set(extract_title_scam_phrases(row.get("title") or "")):
            title_phrase_docs[phrase] += 1

    crawl_keywords: list[str] = []
    keyword_meta: list[dict] = []

    def add_crawl_keyword(keyword: str, count: int, reason: str) -> None:
        if keyword in crawl_keywords:
            return
        crawl_keywords.append(keyword)
        keyword_meta.append(
            {
                "keyword": keyword,
                "doc_count": count,
                "use_for_crawl": True,
                "reason": reason,
            }
        )

    # 1) 種子手法詞：在新聞／宣導中夠常見才納入重爬
    for pattern, count in pattern_docs.most_common():
        if pattern in TOO_GENERIC:
            keyword_meta.append(
                {
                    "keyword": pattern,
                    "doc_count": count,
                    "use_for_crawl": False,
                    "reason": "too_generic",
                }
            )
            continue
        if count < min_docs:
            keyword_meta.append(
                {
                    "keyword": pattern,
                    "doc_count": count,
                    "use_for_crawl": False,
                    "reason": "below_min_docs",
                }
            )
            continue
        if not is_clean_method_keyword(pattern):
            keyword_meta.append(
                {
                    "keyword": pattern,
                    "doc_count": count,
                    "use_for_crawl": False,
                    "reason": "rejected_noisy",
                }
            )
            continue
        add_crawl_keyword(pattern, count, "seed_pattern_frequent_in_news")

    # 2) 研究必備手法詞（即使本批新聞較少）
    must_include = [
        "假投資",
        "假交友",
        "假貸款",
        "假檢警",
        "假客服",
        "假房東",
        "人頭戶",
        "一頁式",
        "網購詐騙",
        "交友詐騙",
        "投資詐騙",
        "租屋詐騙",
        "求職詐騙",
        "虛擬貨幣",
        "釣魚",
        "驗證碼",
        "OTP",
    ]
    for keyword in must_include:
        add_crawl_keyword(
            keyword, pattern_docs.get(keyword, 0), "must_include_for_case_search"
        )

    # 3) 標題短語只記錄，不自動重爬（避免新聞標題碎片）
    observed_title_phrases = [
        {"phrase": phrase, "doc_count": count}
        for phrase, count in title_phrase_docs.most_common(50)
    ]

    return {
        "source_csv": ptt_csv,
        "source_article_count": len(rows),
        "news_info_article_count": used_rows,
        "extracted_on": date.today().isoformat(),
        "crawl_keywords": crawl_keywords,
        "keyword_meta": keyword_meta,
        "observed_title_phrases_not_auto_crawled": observed_title_phrases,
        "notes": (
            "Step A: count method keywords inside news/PSA Bunco posts. "
            "Step B: keep only clean method phrases for re-crawl. "
            "Title fragments are observed but not auto-used as search queries. "
            "Generic terms (AI/廣告/投資/LINE…) are excluded from crawl."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract scam-method keywords from news/PSA PTT CSV"
    )
    parser.add_argument("--ptt", default="ptt_scam_cases.csv")
    parser.add_argument("--min-docs", type=int, default=3)
    parser.add_argument(
        "--output",
        default="",
        help="預設 data/raw/scam_keywords_from_news_YYYYMMDD.json",
    )
    args = parser.parse_args()

    payload = extract_keywords_from_ptt_csv(args.ptt, min_docs=args.min_docs)
    out = args.output or f"data/raw/scam_keywords_from_news_{date.today().strftime('%Y%m%d')}.json"
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("==== Keyword extraction ====")
    print(f"source articles: {payload['source_article_count']}")
    print(f"news/info used: {payload['news_info_article_count']}")
    print(f"crawl_keywords ({len(payload['crawl_keywords'])}):")
    for keyword in payload["crawl_keywords"]:
        print(f"  - {keyword}")
    print(f"output: {path}")


if __name__ == "__main__":
    main()
