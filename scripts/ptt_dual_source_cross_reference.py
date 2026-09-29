"""
PTT 文章正文 URL 與兩個官方資料源「分開」cross-reference（研究用）。

資料源（不合併黑名單）：
  1. 176455 — data/raw/NPA_WEBURL_*.csv（遭停止解析涉詐網域）
     → Exact / Fuzzy / Non-match（沿用既有研究定義）
  2. 160055 — data/raw/NPA_FAKE_INVEST_*.csv（假投資／博弈週統計）
     → 僅輸出 matches（不稱為 Exact / Fuzzy / Non-match）

不建立 scam / non-scam label，不做人工判斷。
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path

from scripts.ptt_165_cross_reference import (
    DEFAULT_SEED,
    NormalizedUrl,
    UrlMatchRow,
    classify_url,
    extract_urls_from_content,
    normalize_extracted_url,
    registrable_domain,
    sample_count,
    strip_trailing_punct,
    write_csv,
)

# ---------------------------------------------------------------------------
# 160055 專用 normalization（與 176455 / scam_165_urls 規則分開說明）
# ---------------------------------------------------------------------------
#
# 官方欄位「網址」常見型態：
#   - www.example.com
#   - example.com/path
#   - 偶有完整 http(s) URL
#   - 可能含子路徑、罕見含 query
#
# 本模組對 160055「網址」欄位的規則（僅用於建立 160055 索引與比對鍵）：
#   1. strip 空白與文末標點（與 PTT 抽出 URL 的清理一致，避免句號黏連）
#   2. 若無 scheme，補上 http:// 再解析（160055 多數無 scheme）
#   3. hostname / path 皆 lower-case；host 去掉前綴 www.
#   4. path 去掉尾端 /，組成 host 或 host+path 鍵
#   5. 不套用 176455 的 shortener → fuzzy 分層；160055 只產出 match / 未命中
#   6. 不使用 160055 的「網站名稱」做 URL 比對（避免同名不同站誤判）
#


def normalize_160055_url(raw: str) -> NormalizedUrl:
    """160055 網址欄位專用 normalization（規則見模組註解）。"""
    cleaned = strip_trailing_punct((raw or "").strip())
    # 機械步驟與 PTT 抽出後解析相同，但語意上屬 160055 規則，呼叫點分開
    return normalize_extracted_url(cleaned)


def load_176455_index(csv_path: str) -> tuple[set[str], set[str], dict[str, str]]:
    """
    從官方 NPA_WEBURL（民國年月,網域,...）建立索引。
    鍵為 normalize_extracted_url(網域) 後的 host / host_path。
    """
    hosts: set[str] = set()
    host_paths: set[str] = set()
    host_example: dict[str, str] = {}

    with open(csv_path, "r", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        for row in reader:
            domain = (row.get("網域") or "").strip()
            if not domain:
                continue
            nu = normalize_extracted_url(domain)
            if not nu.normalized_host:
                continue
            hosts.add(nu.normalized_host)
            host_paths.add(nu.normalized_host_path)
            host_example.setdefault(nu.normalized_host, domain)
            host_example.setdefault(nu.normalized_host_path, domain)

    return hosts, host_paths, host_example


def load_160055_index(csv_path: str) -> tuple[set[str], set[str], dict[str, dict]]:
    """
    從官方假投資(博弈) CSV 建立索引。
    回傳 (hosts, host_paths, key_to_example)；example 含網站名稱與原始網址。
    """
    hosts: set[str] = set()
    host_paths: set[str] = set()
    key_to_example: dict[str, dict] = {}

    with open(csv_path, "r", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        for row in reader:
            web = (row.get("網址") or "").strip()
            name = (row.get("網站名稱") or "").strip()
            if not web:
                continue
            nu = normalize_160055_url(web)
            if not nu.normalized_host:
                continue
            example = {
                "matched_160055_site_name": name,
                "matched_160055_url": web,
                "matched_160055_sta_sdate": (row.get("統計起始日期") or "").strip(),
                "matched_160055_sta_edate": (row.get("統計結束日期") or "").strip(),
            }
            hosts.add(nu.normalized_host)
            host_paths.add(nu.normalized_host_path)
            key_to_example.setdefault(nu.normalized_host, example)
            key_to_example.setdefault(nu.normalized_host_path, example)

    return hosts, host_paths, key_to_example


def classify_160055_match(
    nu: NormalizedUrl,
    hosts: set[str],
    host_paths: set[str],
    key_to_example: dict[str, dict],
) -> dict | None:
    """
    160055 命中規則（皆標為 match，不分成 Exact/Fuzzy）：

      A. normalized_host 等於 160055 索引 host
      B. normalized_host_path 等於 160055 索引 host_path
      C. extracted host 為某 160055 host 的子網域（endswith .scam_host）
      D. registrable_domain 等於 160055 host，但 full host 不同

    不含 shortener 自動命中（與 176455 fuzzy 不同）。
    """
    if not nu.normalized_host:
        return None

    if nu.normalized_host in hosts:
        ex = key_to_example.get(nu.normalized_host, {})
        return {
            "match_reason": "normalized_host equals 160055 host",
            **ex,
        }

    if nu.normalized_host_path in host_paths:
        ex = key_to_example.get(nu.normalized_host_path, {})
        return {
            "match_reason": "normalized_host_path equals 160055 host_path",
            **ex,
        }

    for scam_host in hosts:
        if len(scam_host) < 5:
            continue
        if nu.normalized_host.endswith("." + scam_host):
            ex = key_to_example.get(scam_host, {})
            return {
                "match_reason": "extracted host is subdomain of 160055 host",
                **ex,
            }

    reg = registrable_domain(nu.normalized_host)
    if reg in hosts and reg != nu.normalized_host:
        ex = key_to_example.get(reg, {})
        return {
            "match_reason": "registrable_domain matches 160055 host but full host differs",
            **ex,
        }

    return None


OUTPUT_160055_FIELDS = [
    "title",
    "article_url",
    "published_at",
    "extracted_url",
    "normalized_url_160055",
    "matched_160055_url",
    "matched_160055_site_name",
    "matched_160055_sta_sdate",
    "matched_160055_sta_edate",
    "match_reason",
    "review_status",
    "random_seed",
]


@dataclass
class Match160055Row:
    title: str
    article_url: str
    published_at: str
    extracted_url: str
    normalized_url_160055: str
    matched_160055_url: str
    matched_160055_site_name: str
    matched_160055_sta_sdate: str
    matched_160055_sta_edate: str
    match_reason: str
    review_status: str = "pending"
    random_seed: str = ""


def write_160055_csv(path: Path, rows: list[Match160055Row], seed: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=OUTPUT_160055_FIELDS)
        writer.writeheader()
        for row in rows:
            data = asdict(row)
            data["random_seed"] = data["random_seed"] or str(seed)
            writer.writerow(data)


def run_dual_source(
    ptt_csv: str,
    csv_176455: str,
    csv_160055: str,
    output_dir: str,
    seed: int = DEFAULT_SEED,
) -> dict:
    hosts_176455, paths_176455, example_176455 = load_176455_index(csv_176455)
    hosts_160055, paths_160055, example_160055 = load_160055_index(csv_160055)

    with open(ptt_csv, "r", encoding="utf-8-sig") as file:
        ptt_rows = list(csv.DictReader(file))

    exact_rows: list[UrlMatchRow] = []
    fuzzy_rows: list[UrlMatchRow] = []
    non_match_articles: list[UrlMatchRow] = []
    matches_160055: list[Match160055Row] = []

    # 用於雙源重疊：以 (article_url, extracted_url) 為鍵
    keys_176455_hit: set[tuple[str, str]] = set()
    keys_160055_hit: set[tuple[str, str]] = set()
    articles_176455_exact: set[str] = set()
    articles_176455_fuzzy: set[str] = set()
    articles_160055: set[str] = set()

    articles_with_url = 0
    total_extracted_urls = 0

    for article in ptt_rows:
        title = article.get("title") or ""
        article_url = article.get("url") or ""
        published_at = article.get("published_at") or ""
        content = article.get("content") or ""

        extracted = extract_urls_from_content(content)
        if extracted:
            articles_with_url += 1
            total_extracted_urls += len(extracted)

        article_has_exact = False
        article_has_fuzzy = False

        for raw_url in extracted:
            nu_176455 = normalize_extracted_url(raw_url)
            matched_176455 = classify_url(
                nu_176455, hosts_176455, paths_176455, example_176455
            )
            if matched_176455:
                matched_176455.title = title
                matched_176455.article_url = article_url
                matched_176455.published_at = published_at
                pair = (article_url, raw_url)
                keys_176455_hit.add(pair)
                if matched_176455.match_type == "exact_match":
                    exact_rows.append(matched_176455)
                    article_has_exact = True
                    articles_176455_exact.add(article_url)
                elif matched_176455.match_type == "fuzzy_match":
                    fuzzy_rows.append(matched_176455)
                    article_has_fuzzy = True
                    articles_176455_fuzzy.add(article_url)

            nu_160055 = normalize_160055_url(raw_url)
            hit_160055 = classify_160055_match(
                nu_160055, hosts_160055, paths_160055, example_160055
            )
            if hit_160055:
                matches_160055.append(
                    Match160055Row(
                        title=title,
                        article_url=article_url,
                        published_at=published_at,
                        extracted_url=raw_url,
                        normalized_url_160055=nu_160055.normalized_host_path,
                        matched_160055_url=hit_160055.get("matched_160055_url", ""),
                        matched_160055_site_name=hit_160055.get(
                            "matched_160055_site_name", ""
                        ),
                        matched_160055_sta_sdate=hit_160055.get(
                            "matched_160055_sta_sdate", ""
                        ),
                        matched_160055_sta_edate=hit_160055.get(
                            "matched_160055_sta_edate", ""
                        ),
                        match_reason=hit_160055.get("match_reason", ""),
                    )
                )
                keys_160055_hit.add((article_url, raw_url))
                articles_160055.add(article_url)

        if not article_has_exact and not article_has_fuzzy:
            non_match_articles.append(
                UrlMatchRow(
                    title=title,
                    article_url=article_url,
                    published_at=published_at,
                    extracted_url="",
                    normalized_url="",
                    matched_165_url="",
                    match_type="non_match",
                    match_reason=(
                        "no exact or fuzzy URL correspondence with 176455 "
                        "for this article"
                    ),
                    review_status="pending",
                )
            )

    rng = random.Random(seed)

    exact_sample_n = sample_count(len(exact_rows), cap=100)
    if len(exact_rows) <= exact_sample_n:
        exact_sample = exact_rows
    else:
        exact_sample = rng.sample(exact_rows, exact_sample_n)
    for row in exact_sample:
        row.random_sample_group = "exact_sample"

    for row in fuzzy_rows:
        row.random_sample_group = "fuzzy_full_review"

    non_n = len(non_match_articles)
    non_sample_n = sample_count(non_n, cap=None)
    if non_n <= non_sample_n:
        non_sample = non_match_articles
    else:
        non_sample = rng.sample(non_match_articles, non_sample_n)
    for row in non_sample:
        row.random_sample_group = "non_match_sample"

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    exact_path = out / "176455_exact_matches.csv"
    fuzzy_path = out / "176455_fuzzy_matches_review.csv"
    non_path = out / "176455_non_matches_sample.csv"
    path_160055 = out / "160055_matches.csv"

    write_csv(exact_path, exact_sample, seed)
    write_csv(fuzzy_path, fuzzy_rows, seed)
    write_csv(non_path, non_sample, seed)
    write_160055_csv(path_160055, matches_160055, seed)

    only_176455 = keys_176455_hit - keys_160055_hit
    only_160055 = keys_160055_hit - keys_176455_hit
    both = keys_176455_hit & keys_160055_hit

    articles_176455_any = articles_176455_exact | articles_176455_fuzzy
    articles_only_176455 = articles_176455_any - articles_160055
    articles_only_160055 = articles_160055 - articles_176455_any
    articles_both = articles_176455_any & articles_160055

    # shortener fuzzy 列不算「真命中官方網域」，另計
    fuzzy_shortener = sum(
        1 for r in fuzzy_rows if r.match_reason == "shortener_or_redirect_domain_host"
    )
    fuzzy_domain = len(fuzzy_rows) - fuzzy_shortener

    stats = {
        "ptt_csv": ptt_csv,
        "ptt_article_count": len(ptt_rows),
        "articles_with_url": articles_with_url,
        "total_extracted_urls": total_extracted_urls,
        "random_seed": seed,
        "source_176455_csv": csv_176455,
        "source_176455_unique_hosts": len(hosts_176455),
        "176455_exact_url_rows": len(exact_rows),
        "176455_fuzzy_url_rows": len(fuzzy_rows),
        "176455_fuzzy_shortener_rows": fuzzy_shortener,
        "176455_fuzzy_domain_related_rows": fuzzy_domain,
        "176455_non_match_articles": non_n,
        "176455_exact_sample_rows": len(exact_sample),
        "176455_fuzzy_review_rows": len(fuzzy_rows),
        "176455_non_match_sample_rows": len(non_sample),
        "176455_articles_exact": sorted(articles_176455_exact),
        "176455_articles_fuzzy": sorted(articles_176455_fuzzy),
        "source_160055_csv": csv_160055,
        "source_160055_unique_hosts": len(hosts_160055),
        "160055_match_url_rows": len(matches_160055),
        "160055_match_articles": len(articles_160055),
        "160055_articles": sorted(articles_160055),
        "overlap_extracted_url_pairs": {
            "only_176455": len(only_176455),
            "only_160055": len(only_160055),
            "both": len(both),
        },
        "overlap_articles": {
            "only_176455": len(articles_only_176455),
            "only_160055": len(articles_only_160055),
            "both": len(articles_both),
            "only_176455_urls": sorted(articles_only_176455),
            "only_160055_urls": sorted(articles_only_160055),
            "both_urls": sorted(articles_both),
        },
        "normalization_notes": {
            "176455": (
                "PTT URL → strip punct, lower, strip www., host / host+path; "
                "Exact = host or host_path in 網域 index; "
                "Fuzzy = shortener host OR subdomain OR registrable_domain overlap"
            ),
            "160055": (
                "Separate rules for 網址 field: strip punct, add http if missing, "
                "lower, strip www., host / host+path. Match reasons A–D only; "
                "no Exact/Fuzzy labels; shortener hosts are NOT auto-matched."
            ),
        },
        "output_files": [
            str(exact_path),
            str(fuzzy_path),
            str(non_path),
            str(path_160055),
        ],
        "note": (
            "Blacklists are NOT merged. Previous data/review/*.csv files are left "
            "unchanged. No scam/non-scam labels assigned."
        ),
    }

    summary_path = out / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as file:
        json.dump(stats, file, ensure_ascii=False, indent=2)
    stats["summary_json"] = str(summary_path)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PTT vs 176455 + 160055 dual-source URL cross-reference"
    )
    parser.add_argument("--ptt", default="ptt_scam_cases.csv")
    parser.add_argument(
        "--csv-176455", default="data/raw/NPA_WEBURL_20260930.csv"
    )
    parser.add_argument(
        "--csv-160055", default="data/raw/NPA_FAKE_INVEST_20260930.csv"
    )
    parser.add_argument(
        "--output-dir", default="data/review/run_20260930_dual_source"
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()

    stats = run_dual_source(
        args.ptt,
        args.csv_176455,
        args.csv_160055,
        args.output_dir,
        seed=args.seed,
    )

    print("==== PTT Dual-Source Cross-Reference ====")
    for key in (
        "ptt_article_count",
        "articles_with_url",
        "total_extracted_urls",
        "176455_exact_url_rows",
        "176455_fuzzy_url_rows",
        "176455_non_match_articles",
        "160055_match_url_rows",
        "160055_match_articles",
        "overlap_extracted_url_pairs",
        "overlap_articles",
        "output_files",
        "random_seed",
    ):
        print(f"{key}: {stats[key]}")


if __name__ == "__main__":
    main()
