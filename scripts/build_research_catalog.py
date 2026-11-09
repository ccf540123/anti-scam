"""Read existing research files and write docs/review/research_catalog.json.

Does not crawl, does not write Supabase, and does not edit source CSVs.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "review" / "research_catalog.json"


def load_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def canon(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
        path = parsed.path.rstrip("/")
        return parsed.scheme + "://" + parsed.netloc.lower() + path
    except Exception:
        return raw


def file_time(path: Path) -> str:
    stamp = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def year_of(value: str) -> int | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%a %b %d %H:%M:%S %Y").year
    except ValueError:
        return None


def host_of(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "http://" + raw
    try:
        host = (urlparse(raw).hostname or "").lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def blank(value: str) -> bool:
    return not str(value or "").strip()


def main() -> None:
    ptt_path = ROOT / "ptt_scam_cases.csv"
    stage1_path = ROOT / "docs" / "review" / "items.csv"
    stage2_path = ROOT / "docs" / "review" / "stage2_items.csv"
    team_path = ROOT / "data" / "stage2_probe" / "team_keywords_ptt.csv"
    status_path = ROOT / "data" / "review" / "run_stage1_pipeline" / "ptt_article1_status.csv"
    fuzzy_path = ROOT / "data" / "review" / "run_stage1_pipeline" / "176455_fuzzy_matches_review.csv"
    fake_match_path = ROOT / "data" / "review" / "run_stage1_pipeline" / "160055_matches.csv"
    exact_path = ROOT / "data" / "review" / "run_stage1_pipeline" / "176455_exact_matches.csv"
    web_path = ROOT / "data" / "raw" / "NPA_WEBURL_20260930.csv"
    fake_path = ROOT / "data" / "raw" / "NPA_FAKE_INVEST_20260930.csv"
    runtime_path = ROOT / "scam_165_urls.csv"
    web_meta_path = ROOT / "data" / "raw" / "NPA_WEBURL_20260930.meta.json"
    fake_meta_path = ROOT / "data" / "raw" / "NPA_FAKE_INVEST_20260930.meta.json"

    ptt = load_csv(ptt_path)
    stage1 = load_csv(stage1_path)
    stage2 = load_csv(stage2_path)
    team = load_csv(team_path)
    status_rows = load_csv(status_path)
    fuzzy_rows = load_csv(fuzzy_path)
    fake_matches = load_csv(fake_match_path)
    exact_rows = load_csv(exact_path)
    web_rows = load_csv(web_path)
    fake_rows = load_csv(fake_path)
    runtime_rows = load_csv(runtime_path)
    web_meta = json.loads(web_meta_path.read_text(encoding="utf-8"))
    fake_meta = json.loads(fake_meta_path.read_text(encoding="utf-8"))

    groups = {
        "ptt_crawl": ptt,
        "stage1": stage1,
        "stage2": stage2,
        "team_keywords": team,
    }
    url_keys = {
        "ptt_crawl": "url",
        "stage1": "article_url",
        "stage2": "article_url",
        "team_keywords": "url",
    }
    sets = {
        key: {canon(row[url_keys[key]]) for row in rows if canon(row[url_keys[key]])}
        for key, rows in groups.items()
    }
    labels = {
        "ptt_crawl": "PTT 爬蟲清單",
        "stage1": "第一階段審查清單",
        "stage2": "第二階段審查清單",
        "team_keywords": "team keywords 搜尋結果",
    }
    sources = {
        "ptt_crawl": ("ptt_scam_cases.csv", ptt_path),
        "stage1": ("docs/review/items.csv", stage1_path),
        "stage2": ("docs/review/stage2_items.csv", stage2_path),
        "team_keywords": ("data/stage2_probe/team_keywords_ptt.csv", team_path),
    }

    datasets = []
    for key in ("ptt_crawl", "stage1", "stage2", "team_keywords"):
        rows = groups[key]
        source_label, path = sources[key]
        missing_date = sum(1 for row in rows if year_of(row.get("published_at", "")) is None)
        datasets.append(
            {
                "id": key,
                "label": labels[key],
                "rows": len(rows),
                "unique_urls": len(sets[key]),
                "source": source_label,
                "file_updated_at": file_time(path),
                "missing_dates": missing_date,
                "ai": None,
            }
        )

    order = ["ptt_crawl", "stage1", "stage2", "team_keywords"]
    pairs = []
    for index, left in enumerate(order):
        for right in order[index + 1 :]:
            both = sets[left] & sets[right]
            pairs.append(
                {
                    "a": left,
                    "b": right,
                    "both": len(both),
                    "only_a": len(sets[left] - sets[right]),
                    "only_b": len(sets[right] - sets[left]),
                }
            )
    union = set.union(*sets.values())
    only = {
        key: len(sets[key] - set.union(*(sets[other] for other in order if other != key)))
        for key in order
    }
    stage1_urls = sets["stage1"]
    flag_mismatch = 0
    for row in stage2:
        url = canon(row["article_url"])
        flagged = row.get("stage1_flag") == "第一階段已存在"
        inside = url in stage1_urls
        if flagged != inside:
            flag_mismatch += 1

    year_counts = Counter()
    missing_years = 0
    for row in ptt:
        year = year_of(row.get("published_at", ""))
        if year is None:
            missing_years += 1
        else:
            year_counts[year] += 1

    board_counts = Counter((row.get("source_board") or "").strip() or "（看板空白）" for row in ptt)
    keyword_counts = Counter((row.get("search_keyword") or "").strip() or "（關鍵字空白）" for row in ptt)
    team_keyword_counts = Counter(
        (row.get("search_keyword") or "").strip() or "（關鍵字空白）" for row in team
    )

    web_hosts = {(row.get("網域") or "").strip().lower() for row in web_rows if (row.get("網域") or "").strip()}
    fake_hosts = {host_of(row.get("網址", "")) for row in fake_rows}
    fake_hosts.discard("")
    runtime_hosts = {
        (row.get("normalized_url") or "").strip().lower()
        for row in runtime_rows
        if (row.get("normalized_url") or "").strip()
    }

    exact_articles = [row for row in status_rows if (row.get("status") or "").strip() == "exact_match"]
    fuzzy_articles = {canon(row.get("article_url", "")) for row in fuzzy_rows if canon(row.get("article_url", ""))}
    fake_article_urls = {canon(row.get("article_url", "")) for row in fake_matches if canon(row.get("article_url", ""))}
    exact_status_urls = {canon(row.get("url", "")) for row in exact_articles if canon(row.get("url", ""))}

    articles = {}

    def ensure(url: str) -> dict:
        key = canon(url)
        if key not in articles:
            articles[key] = {
                "case_id": "",
                "title": "",
                "url": url,
                "published_at": "",
                "year": None,
                "boards": [],
                "search_keywords": [],
                "datasets": [],
                "stage1_review_id": "",
                "stage2_review_id": "",
                "stage1_flag": "",
                "official_exact_status": False,
                "official_fake_invest_match": False,
                "official_fuzzy_shortener": False,
                "ai": None,
            }
        return articles[key]

    def add_text(item: dict, field: str, value: str) -> None:
        text = (value or "").strip()
        if text and text not in item[field]:
            item[field].append(text)

    for row in ptt:
        item = ensure(row["url"])
        item["title"] = item["title"] or row.get("title") or ""
        item["published_at"] = item["published_at"] or row.get("published_at") or ""
        add_text(item, "boards", row.get("source_board", ""))
        add_text(item, "search_keywords", row.get("search_keyword", ""))
        if "ptt_crawl" not in item["datasets"]:
            item["datasets"].append("ptt_crawl")
    for row in stage1:
        item = ensure(row["article_url"])
        item["title"] = item["title"] or row.get("title") or ""
        item["published_at"] = item["published_at"] or row.get("published_at") or ""
        item["stage1_review_id"] = row.get("review_id") or ""
        add_text(item, "boards", row.get("source_board", ""))
        add_text(item, "search_keywords", row.get("search_keyword", ""))
        if "stage1" not in item["datasets"]:
            item["datasets"].append("stage1")
    for row in stage2:
        item = ensure(row["article_url"])
        item["title"] = item["title"] or row.get("title") or ""
        item["published_at"] = item["published_at"] or row.get("published_at") or ""
        item["stage2_review_id"] = row.get("review_id") or ""
        item["stage1_flag"] = row.get("stage1_flag") or ""
        add_text(item, "boards", row.get("source_board", ""))
        for part in (row.get("search_keyword") or "").split("、"):
            add_text(item, "search_keywords", part)
        if "stage2" not in item["datasets"]:
            item["datasets"].append("stage2")
    for row in team:
        item = ensure(row["url"])
        item["title"] = item["title"] or row.get("title") or ""
        item["published_at"] = item["published_at"] or row.get("published_at") or ""
        add_text(item, "boards", row.get("source_board", ""))
        add_text(item, "search_keywords", row.get("search_keyword", ""))
        if "team_keywords" not in item["datasets"]:
            item["datasets"].append("team_keywords")

    for item in articles.values():
        item["year"] = year_of(item["published_at"])
        item["official_exact_status"] = canon(item["url"]) in exact_status_urls
        item["official_fake_invest_match"] = canon(item["url"]) in fake_article_urls
        item["official_fuzzy_shortener"] = canon(item["url"]) in fuzzy_articles
        seed = item["stage1_review_id"] or item["stage2_review_id"] or canon(item["url"])
        if item["stage1_review_id"] or item["stage2_review_id"]:
            item["case_id"] = item["stage1_review_id"] or item["stage2_review_id"]
        else:
            item["case_id"] = "url_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]

    catalog = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ai": None,
        "datasets": datasets,
        "overlap": {
            "pairs": pairs,
            "only": only,
            "union_urls": len(union),
            "stage1_flag_mismatches": flag_mismatch,
            "note": "union_urls 是四份清單的不重複文章網址，不是確認案例數，也不能把四份筆數相加。",
        },
        "years": {
            "source": "ptt_scam_cases.csv",
            "missing": missing_years,
            "counts": [{"year": year, "rows": year_counts[year]} for year in sorted(year_counts)],
        },
        "boards": {
            "source": "ptt_scam_cases.csv",
            "counts": [{"name": name, "rows": board_counts[name]} for name in sorted(board_counts, key=lambda name: (-board_counts[name], name))],
        },
        "search_keywords": {
            "source": "ptt_scam_cases.csv",
            "counts": [{"name": name, "rows": keyword_counts[name]} for name in sorted(keyword_counts, key=lambda name: (-keyword_counts[name], name))],
        },
        "team_search_keywords": {
            "source": "data/stage2_probe/team_keywords_ptt.csv",
            "counts": [
                {"name": name, "rows": team_keyword_counts[name]}
                for name in sorted(team_keyword_counts, key=lambda name: (-team_keyword_counts[name], name))
            ],
        },
        "official": {
            "weburl": {
                "label": "165 停止解析網站名單",
                "file": "data/raw/NPA_WEBURL_20260930.csv",
                "snapshot_date": web_meta.get("download_date", ""),
                "rows": len(web_rows),
                "unique_hosts": len(web_hosts),
                "host_rule": "網域欄去掉空白並轉成小寫後的不重複值。有些列含路徑，所以這不是純主機名稱數。",
                "meaning": "官方網站名單的列數。不是 PTT 文章，也不是已確認案例數。",
            },
            "fake_invest": {
                "label": "165 假投資網站名單",
                "file": "data/raw/NPA_FAKE_INVEST_20260930.csv",
                "snapshot_date": fake_meta.get("download_date", ""),
                "rows": len(fake_rows),
                "unique_hosts": len(fake_hosts),
                "meaning": "官方假投資（博弈）網站名單。沒有和停止解析名單合併。",
            },
            "runtime_blacklist": {
                "label": "偵測用 165 黑名單",
                "file": "scam_165_urls.csv",
                "file_updated_at": file_time(runtime_path),
                "rows": len(runtime_rows),
                "unique_hosts": len(runtime_hosts),
                "meaning": "公開檢測第一關使用的網址清單。沒有網站性質，也不是文章。",
            },
            "weburl_exact_url_rows": len(exact_rows),
            "article_exact_status": len(exact_articles),
            "fake_invest_match_articles": len(fake_article_urls),
            "fuzzy_url_rows": len(fuzzy_rows),
            "fuzzy_articles": len(fuzzy_articles),
            "fuzzy_meaning": "文章裡的縮網址和官方網域有模糊訊號。不是精確命中，也不是已確認詐騙案例。",
        },
        "articles": sorted(articles.values(), key=lambda item: item["published_at"] or "", reverse=True),
    }
    OUT.write_text(json.dumps(catalog, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("wrote", OUT)
    print("datasets", [(item["id"], item["rows"]) for item in datasets])
    print("union", len(union), "flag_mismatch", flag_mismatch)
    print("exact_status", len(exact_articles), "fake_articles", len(fake_article_urls), "fuzzy_articles", len(fuzzy_articles), "exact_url_rows", len(exact_rows))
    print("web_hosts", len(web_hosts), "fake_hosts", len(fake_hosts), "runtime_hosts", len(runtime_hosts))
    print("articles", len(articles))


if __name__ == "__main__":
    main()
