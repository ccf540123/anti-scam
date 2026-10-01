"""
PTT 文章正文 URL 與 165 黑名單 cross-reference（研究用）。

第一階段 Article 1 自動流程：
  PTT raw → 從 content 抽 URL → normalization
    ├─ exact_match（官方 URL exact）→ Article 1 status = exact_match
    ├─ fuzzy_match（研究用；≠ temp / non_match）→ 仍進 Fuzzy Review
    └─ 無 exact → Article 1 status = temp（等待人工；不是 non_match）

不建立 scam / non-scam label。
non_match 不由本自動流程產生。
"""

from __future__ import annotations

import argparse
import csv
import math
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urlparse

from scripts.article1_status import (
    ARTICLE1_STATUS_EXACT_MATCH,
    ARTICLE1_STATUS_TEMP,
    classify_article1_status,
)

# 沿用既有 regex 起點，但在此模組內做清理與研究用 normalization
URL_PATTERN = re.compile(
    r"(https?://[^\s]+|www\.[^\s]+|[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/[^\s]*)?)"
)

TRAILING_JUNK = ")]}>,.;:!?'\"，。、」』】》"

# 常見短網址／轉址（僅 host 比對，不追 redirect）
SHORTENER_HOSTS = {
    "reurl.cc",
    "bit.ly",
    "tinyurl.com",
    "goo.gl",
    "t.co",
    "lin.ee",
    "pse.is",
    "p.asia",
    "0rz.tw",
    "ppt.cc",  # 不是 PTT 文章 url；若正文誤抽 ppt.cc 可標 fuzzy
}

OUTPUT_FIELDS = [
    "title",
    "article_url",
    "published_at",
    "extracted_url",
    "normalized_url",
    "matched_165_url",
    "match_type",
    "match_reason",
    "review_status",
    "random_sample_group",
    "random_seed",
]

DEFAULT_SEED = 42


@dataclass
class NormalizedUrl:
    raw_extracted: str
    cleaned_extracted: str
    normalized_host: str
    normalized_host_path: str


@dataclass
class UrlMatchRow:
    title: str
    article_url: str
    published_at: str
    extracted_url: str
    normalized_url: str
    matched_165_url: str
    match_type: str
    match_reason: str
    review_status: str = "pending"
    random_sample_group: str = ""
    random_seed: str = ""


def strip_trailing_punct(url: str) -> str:
    value = url.strip()
    while value and value[-1] in TRAILING_JUNK:
        value = value[:-1]
    return value


def extract_urls_from_content(content: str) -> list[str]:
    if not content:
        return []
    found = URL_PATTERN.findall(content)
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in found:
        c = strip_trailing_punct(item)
        if not c or c in seen:
            continue
        seen.add(c)
        cleaned.append(c)
    return cleaned


def normalize_extracted_url(raw: str) -> NormalizedUrl:
    cleaned = strip_trailing_punct(raw)
    candidate = cleaned
    if not candidate.lower().startswith(("http://", "https://")):
        candidate = "http://" + candidate

    parsed = urlparse(unquote(candidate.lower()))
    host = (parsed.hostname or "").strip()
    if host.startswith("www."):
        host = host[4:]

    path = (parsed.path or "").rstrip("/")
    host_path = host + path if path else host

    return NormalizedUrl(
        raw_extracted=raw,
        cleaned_extracted=cleaned,
        normalized_host=host,
        normalized_host_path=host_path,
    )


def load_165_index(csv_path: str) -> tuple[set[str], set[str], dict[str, str]]:
    """
    回傳 (host_set, host_path_set, host_to_example_weburl)
    165 本地 CSV 的 normalized_url 目前幾乎都是 host。
    """
    hosts: set[str] = set()
    host_paths: set[str] = set()
    host_example: dict[str, str] = {}

    with open(csv_path, "r", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        for row in reader:
            weburl = (row.get("weburl") or "").strip()
            norm = (row.get("normalized_url") or "").strip().lower()
            if not norm:
                continue
            hosts.add(norm)
            host_paths.add(norm)
            host_example.setdefault(norm, weburl)
            # 若原始 weburl 含 path，再補一筆 host+path key
            nu = normalize_extracted_url(weburl if "://" in weburl else "http://" + weburl)
            if nu.normalized_host_path:
                host_paths.add(nu.normalized_host_path)
                host_example.setdefault(nu.normalized_host_path, weburl)

    return hosts, host_paths, host_example


def registrable_domain(host: str) -> str:
    parts = host.split(".")
    if len(parts) < 2:
        return host
    if parts[-2] in {"com", "edu", "gov", "org", "net", "tw"} and len(parts) >= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def classify_url(nu: NormalizedUrl, hosts: set[str], host_paths: set[str], host_example: dict[str, str]) -> UrlMatchRow | None:
    """回傳 match row；若此 URL 對 165 無 reasonable 對應則回 None。"""
    base_kwargs = {
        "extracted_url": nu.raw_extracted,
        "normalized_url": nu.normalized_host_path,
        "review_status": "pending",
    }

    if not nu.normalized_host:
        return None

    # --- Exact ---
    if nu.normalized_host in hosts:
        return UrlMatchRow(
            **base_kwargs,
            matched_165_url=host_example.get(nu.normalized_host, nu.normalized_host),
            match_type="exact_match",
            match_reason="normalized_host equals 165 normalized_url",
            title="",
            article_url="",
            published_at="",
        )

    if nu.normalized_host_path in host_paths:
        return UrlMatchRow(
            **base_kwargs,
            matched_165_url=host_example.get(nu.normalized_host_path, nu.normalized_host_path),
            match_type="exact_match",
            match_reason="normalized_host_path equals 165 entry",
            title="",
            article_url="",
            published_at="",
        )

    # --- Fuzzy (明確規則，不用相似度 threshold) ---
    if nu.normalized_host in SHORTENER_HOSTS:
        return UrlMatchRow(
            **base_kwargs,
            matched_165_url="",
            match_type="fuzzy_match",
            match_reason="shortener_or_redirect_domain_host",
            title="",
            article_url="",
            published_at="",
        )

    reg = registrable_domain(nu.normalized_host)
    if reg in hosts and reg != nu.normalized_host:
        return UrlMatchRow(
            **base_kwargs,
            matched_165_url=host_example.get(reg, reg),
            match_type="fuzzy_match",
            match_reason="registrable_domain matches 165 host but full host differs (possible subdomain/sibling)",
            title="",
            article_url="",
            published_at="",
        )

    for scam_host in hosts:
        if len(scam_host) < 5:
            continue
        if nu.normalized_host.endswith("." + scam_host):
            return UrlMatchRow(
                **base_kwargs,
                matched_165_url=host_example.get(scam_host, scam_host),
                match_type="fuzzy_match",
                match_reason="extracted host is subdomain of 165 host",
                title="",
                article_url="",
                published_at="",
            )

    return None


def sample_count(n: int, ratio_low: float = 0.05, ratio_high: float = 0.10, cap: int | None = 100) -> int:
    if n <= 0:
        return 0
    low = math.ceil(n * ratio_low)
    high = math.ceil(n * ratio_high)
    target = max(low, min(high, n))
    if cap is not None:
        target = min(target, cap)
    return min(n, max(1, target)) if n > 0 else 0


def write_csv(path: Path, rows: Iterable[UrlMatchRow], seed: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "title": row.title,
                    "article_url": row.article_url,
                    "published_at": row.published_at,
                    "extracted_url": row.extracted_url,
                    "normalized_url": row.normalized_url,
                    "matched_165_url": row.matched_165_url,
                    "match_type": row.match_type,
                    "match_reason": row.match_reason,
                    "review_status": row.review_status,
                    "random_sample_group": row.random_sample_group,
                    "random_seed": row.random_seed or str(seed),
                }
            )


def write_article1_status_csv(
    path: Path,
    source_rows: list[dict],
    status_by_url: dict[str, dict],
) -> None:
    """保留原始 Article 1 欄位，並加上 status（temp / exact_match）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    base_fields: list[str] = list(source_rows[0].keys()) if source_rows else []
    for required in (
        "title",
        "url",
        "content",
        "source",
        "published_at",
        "source_board",
        "search_keyword",
    ):
        if required not in base_fields:
            base_fields.append(required)

    extra = ["status", "status_reason", "has_fuzzy_url_signal", "matched_official_url"]
    fieldnames = [f for f in base_fields if f not in extra] + extra

    with open(path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in source_rows:
            article_url = (row.get("url") or "").strip()
            meta = status_by_url.get(article_url) or {
                "status": ARTICLE1_STATUS_TEMP,
                "status_reason": "no_exact_url_match_waiting_human_review",
                "has_fuzzy_url_signal": "no",
                "matched_official_url": "",
            }
            out = dict(row)
            out.update(meta)
            writer.writerow(out)


def run_cross_reference(
    ptt_csv: str,
    scam165_csv: str,
    output_dir: str,
    seed: int = DEFAULT_SEED,
) -> dict:
    hosts, host_paths, host_example = load_165_index(scam165_csv)

    with open(ptt_csv, "r", encoding="utf-8-sig") as file:
        ptt_rows = list(csv.DictReader(file))

    exact_rows: list[UrlMatchRow] = []
    fuzzy_rows: list[UrlMatchRow] = []
    # 無 exact、亦無 fuzzy URL signal 的 Article 1 → temp（不是 non_match）
    temp_no_url_signal_articles: list[UrlMatchRow] = []
    status_by_url: dict[str, dict] = {}

    articles_with_url = 0
    total_extracted_urls = 0
    exact_article_count = 0
    temp_article_count = 0

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
        matched_official = ""

        for raw_url in extracted:
            nu = normalize_extracted_url(raw_url)
            matched = classify_url(nu, hosts, host_paths, host_example)
            if not matched:
                continue

            matched.title = title
            matched.article_url = article_url
            matched.published_at = published_at

            if matched.match_type == "exact_match":
                exact_rows.append(matched)
                article_has_exact = True
                if not matched_official:
                    matched_official = matched.matched_165_url
            elif matched.match_type == "fuzzy_match":
                fuzzy_rows.append(matched)
                article_has_fuzzy = True

        status = classify_article1_status(has_exact_url_match=article_has_exact)
        if status == ARTICLE1_STATUS_EXACT_MATCH:
            exact_article_count += 1
            status_reason = "official_url_exact_match"
        else:
            temp_article_count += 1
            if article_has_fuzzy:
                status_reason = "no_exact_match_has_fuzzy_signal_waiting_human_review"
            else:
                status_reason = "no_exact_url_match_waiting_human_review"

        status_by_url[article_url] = {
            "status": status,
            "status_reason": status_reason,
            "has_fuzzy_url_signal": "yes" if article_has_fuzzy else "no",
            "matched_official_url": matched_official,
        }

        if not article_has_exact and not article_has_fuzzy:
            temp_no_url_signal_articles.append(
                UrlMatchRow(
                    title=title,
                    article_url=article_url,
                    published_at=published_at,
                    extracted_url="",
                    normalized_url="",
                    matched_165_url="",
                    match_type=ARTICLE1_STATUS_TEMP,
                    match_reason="no_exact_url_match_waiting_human_review",
                    review_status="pending",
                )
            )

    rng = random.Random(seed)

    exact_sample_n = sample_count(len(exact_rows), cap=100)
    exact_sample = exact_rows if len(exact_rows) <= exact_sample_n else rng.sample(exact_rows, exact_sample_n)
    for row in exact_sample:
        row.random_sample_group = "exact_sample"

    # Fuzzy：接近 100% review → 全部輸出（既有 Fuzzy Review 流程，不破壞）
    for row in fuzzy_rows:
        row.random_sample_group = "fuzzy_full_review"

    temp_n = len(temp_no_url_signal_articles)
    temp_sample_n = sample_count(temp_n, cap=None)
    if temp_n <= temp_sample_n:
        temp_sample = temp_no_url_signal_articles
    else:
        temp_sample = rng.sample(temp_no_url_signal_articles, temp_sample_n)
    for row in temp_sample:
        row.random_sample_group = "temp_sample"

    out = Path(output_dir)
    exact_path = out / "ptt_exact_matches.csv"
    fuzzy_path = out / "ptt_fuzzy_matches_review.csv"
    temp_path = out / "ptt_temp_articles_sample.csv"
    article1_path = out / "ptt_article1_status.csv"

    write_csv(exact_path, exact_sample, seed)
    write_csv(fuzzy_path, fuzzy_rows, seed)
    write_csv(temp_path, temp_sample, seed)
    write_article1_status_csv(article1_path, ptt_rows, status_by_url)

    return {
        "ptt_article_count": len(ptt_rows),
        "articles_with_url": articles_with_url,
        "total_extracted_urls": total_extracted_urls,
        "exact_url_rows": len(exact_rows),
        "fuzzy_url_rows": len(fuzzy_rows),
        "article1_exact_match_articles": exact_article_count,
        "article1_temp_articles": temp_article_count,
        "temp_articles_no_url_signal": temp_n,
        "exact_sample_rows": len(exact_sample),
        "fuzzy_review_rows": len(fuzzy_rows),
        "temp_sample_rows": len(temp_sample),
        "random_seed": seed,
        "output_files": [
            str(exact_path),
            str(fuzzy_path),
            str(temp_path),
            str(article1_path),
        ],
        "165_unique_hosts": len(hosts),
        "note": (
            "Article 1 auto statuses are exact_match|temp only; "
            "non_match is reserved for later human review. "
            "Fuzzy Review CSV is unchanged in role."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="PTT vs 165 URL cross-reference for manual review")
    parser.add_argument("--ptt", default="ptt_scam_cases.csv")
    parser.add_argument("--scam165", default="scam_165_urls.csv")
    parser.add_argument("--output-dir", default="data/review")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()

    stats = run_cross_reference(args.ptt, args.scam165, args.output_dir, seed=args.seed)

    print("==== PTT ↔ 165 Cross-Reference ====")
    for key, value in stats.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
