"""匯出公開資料集 v0.1（CC0）。

只讀內部清單與官方比對狀態，寫入 docs/dataset/。
不連線 Supabase，不讀 .env，不改原始 CSV。

公開檔一律不含 PTT 全文、human_notes、reviewer、evidence_quotes。
人審標籤若要放進凍結檔，請另外提供不含審查者欄位的快照：

    python scripts/export_public_dataset.py --answers-snapshot path/to/answers.csv
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

if __package__ in {None, ""}:
    from pii_patterns import load_rules, redact, render_browser_script
else:
    from scripts.pii_patterns import load_rules, redact, render_browser_script

ROOT = Path(__file__).resolve().parents[1]
RELEASE_VERSION = "v0.1"
LICENSE_ID = "CC0-1.0"
LABEL_MEANING = "topic_relevance_not_scam_truth"
SAMPLING_NOTE = (
    "非隨機樣本。若來源是 grok_batch_01_analysis_v2，"
    "這些篇是從已審、內容相關、較長的文章裡依情境挑選，不是全部文章。"
)

FORBIDDEN_KEYS = {
    "content",
    "human_notes",
    "reviewer",
    "evidence_quotes",
    "reasoning",
    "narrative",
    "narrative_redacted",
    "ip_hash",
    "user_agent_hash",
    "review_notes",
    "reviewed_by",
}

RELEVANCE_FIELDS = [
    "review_id",
    "dataset_type",
    "article_url",
    "url_normalized",
    "title",
    "title_redacted",
    "published_at",
    "year",
    "source",
    "source_board",
    "search_keyword",
    "imported_at",
    "content_char_count",
    "review_status",
    "content_relevant",
    "url_relevant",
    "human_keywords",
    "pipeline_status",
    "stage2_grade",
    "official_match_status",
    "official_fuzzy_url_signal",
    "overlap_with_stage1",
    "also_in_other_list",
    "in_trusted_testset",
    "split",
    "label_meaning",
    "release_version",
]

AI_FIELDS = [
    "review_id",
    "title",
    "title_redacted",
    "source",
    "published_at",
    "url",
    "url_normalized",
    "human_content_relevant",
    "human_url_relevant",
    "human_review_status",
    "article_relevance",
    "case_nature",
    "evidence_level",
    "incident_outcome",
    "outcome_subject",
    "outcome_notes",
    "scam_type",
    "scam_tactics",
    "platforms",
    "suspicious_signals",
    "keywords",
    "victim_situation",
    "event_summary",
    "confidence",
    "analysis_version",
    "source_type",
    "sampling_note",
    "exception_flag",
    "release_version",
    "label_meaning",
]

CROWD_RAG_FIELDS = [
    "submission_id",
    "title_summary",
    "event_summary",
    "scam_type",
    "platforms",
    "evidence_level",
    "incident_outcome",
    "source_type",
    "source_label",
]

ANALYSIS_STAGE1_FIELDS = [
    "review_id",
    "dataset_type",
    "title",
    "article_url",
    "published_at",
    "source",
    "source_board",
    "search_keyword",
    "imported_at",
    "content_char_count",
    "external_hosts",
]

ANALYSIS_STAGE2_FIELDS = ANALYSIS_STAGE1_FIELDS + ["stage1_flag"]


def canon_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return raw
    if not parts.netloc:
        return raw.rstrip("/")
    path = (parts.path or "").rstrip("/")
    return f"{parts.scheme}://{parts.netloc.lower()}{path}"


def year_of(published_at: str) -> int | None:
    match = re.search(r"(?:19|20)\d{2}", published_at or "")
    if not match:
        return None
    return int(match.group(0))


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def hosts_in(text: str) -> list[str]:
    found = []
    seen = set()
    for raw in re.findall(r"https?://[^\s<>\"'）】\]]+", text or ""):
        cleaned = re.sub(r"[),.;:!?，。、]+$", "", raw)
        try:
            host = urlsplit(cleaned).hostname or ""
        except ValueError:
            continue
        host = host.lower()
        if host.startswith("www."):
            host = host[4:]
        if not host or host == "ptt.cc" or host.endswith(".ptt.cc"):
            continue
        if host in seen:
            continue
        seen.add(host)
        found.append(host)
    return found


def official_status(raw_status: str) -> str:
    value = (raw_status or "").strip()
    if value == "exact_match":
        return "exact_match"
    if value == "temp":
        # 內部 article1 的 temp 代表「這份快照沒有 exact URL 命中」，不是詐騙未定。
        return "no_exact_match"
    if value == "non_match":
        return "non_match"
    if not value:
        return "not_in_snapshot"
    return value


def load_official(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    found = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            key = canon_url(row.get("url") or "")
            if not key:
                continue
            fuzzy = (row.get("has_fuzzy_url_signal") or "").strip().lower()
            found[key] = {
                "official_match_status": official_status(row.get("status") or ""),
                "official_fuzzy_url_signal": fuzzy in {"1", "true", "yes", "y"},
            }
    return found


def parse_keywords(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    else:
        text = str(value).strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = re.split(r"[\n、|]", text)
        items = parsed if isinstance(parsed, list) else [text]
    cleaned = []
    seen = set()
    for item in items:
        word = redact(str(item)).strip()
        if not word or word in seen:
            continue
        seen.add(word)
        cleaned.append(word)
    return cleaned


def load_answers(path: Path | None) -> dict[str, dict]:
    if path is None or not path.exists():
        return {}
    answers = {}
    for row in read_csv(path):
        review_id = (row.get("review_id") or "").strip()
        if not review_id:
            continue
        # 快照即使含審查者欄位，這裡也直接丟掉。
        answers[review_id] = {
            "review_status": (row.get("review_status") or "").strip() or "none",
            "content_relevant": (row.get("content_relevant") or "").strip(),
            "url_relevant": (row.get("url_relevant") or "").strip(),
            "human_keywords": parse_keywords(row.get("keywords") or row.get("human_keywords")),
            "pipeline_status": (row.get("status") or row.get("pipeline_status") or "").strip(),
        }
    return answers


def safe_title(title: str) -> tuple[str, bool]:
    original = title or ""
    cleaned = redact(original)
    return cleaned, cleaned != original


def relevance_row(source: dict, answers: dict, official: dict, other_urls: set[str], dataset_type: str) -> dict:
    review_id = (source.get("review_id") or "").strip()
    article_url = source.get("article_url") or ""
    normalized = canon_url(article_url)
    title, title_redacted = safe_title(source.get("title") or "")
    content = source.get("content") or ""
    answer = answers.get(review_id) or {}
    official_row = official.get(normalized) or {
        "official_match_status": "not_in_snapshot",
        "official_fuzzy_url_signal": False,
    }
    grade = ""
    content_relevant = answer.get("content_relevant") or ""
    if dataset_type == "ptt_stage2_keyword" and content_relevant in {"A", "B", "C"}:
        grade = content_relevant
    row = {
        "review_id": review_id,
        "dataset_type": dataset_type,
        "article_url": article_url,
        "url_normalized": normalized,
        "title": title,
        "title_redacted": title_redacted,
        "published_at": source.get("published_at") or "",
        "year": year_of(source.get("published_at") or ""),
        "source": source.get("source") or "",
        "source_board": source.get("source_board") or "",
        "search_keyword": redact(source.get("search_keyword") or ""),
        "imported_at": source.get("imported_at") or "",
        "content_char_count": len(content),
        "review_status": answer.get("review_status") or "none",
        "content_relevant": content_relevant,
        "url_relevant": answer.get("url_relevant") or "",
        "human_keywords": answer.get("human_keywords") or [],
        "pipeline_status": answer.get("pipeline_status") or "",
        "stage2_grade": grade,
        "official_match_status": official_row["official_match_status"],
        "official_fuzzy_url_signal": official_row["official_fuzzy_url_signal"],
        "overlap_with_stage1": dataset_type == "ptt_stage2_keyword" and normalized in other_urls,
        "also_in_other_list": normalized in other_urls,
        "in_trusted_testset": False,
        "split": "unassigned",
        "label_meaning": LABEL_MEANING,
        "release_version": RELEASE_VERSION,
    }
    unknown = set(row) - set(RELEVANCE_FIELDS)
    missing = set(RELEVANCE_FIELDS) - set(row)
    if unknown or missing:
        raise RuntimeError(f"relevance schema drift: extra={unknown} missing={missing}")
    return row


def analysis_row(source: dict, dataset_type: str) -> dict:
    title, _changed = safe_title(source.get("title") or "")
    content = source.get("content") or ""
    row = {
        "review_id": (source.get("review_id") or "").strip(),
        "dataset_type": dataset_type,
        "title": title,
        "article_url": source.get("article_url") or "",
        "published_at": source.get("published_at") or "",
        "source": source.get("source") or "",
        "source_board": source.get("source_board") or "",
        "search_keyword": redact(source.get("search_keyword") or ""),
        "imported_at": source.get("imported_at") or "",
        "content_char_count": len(content),
        "external_hosts": hosts_in(content),
    }
    if dataset_type == "ptt_stage2_keyword":
        row["stage1_flag"] = source.get("stage1_flag") or ""
    return row


def as_list(value) -> list:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [value]
        return parsed if isinstance(parsed, list) else [value]
    return [value]


def public_ai_row(raw: dict, answers: dict) -> dict:
    review_id = str(raw.get("review_id") or "").strip()
    human = raw.get("human_review_status") or {}
    if not isinstance(human, dict):
        human = {}
    answer = answers.get(review_id) or {}
    title, title_redacted = safe_title(str(raw.get("title") or ""))
    url = str(raw.get("url") or raw.get("article_url") or "")
    row = {
        "review_id": review_id,
        "title": title,
        "title_redacted": title_redacted,
        "source": raw.get("source") or "",
        "published_at": raw.get("published_at") or "",
        "url": url,
        "url_normalized": canon_url(url),
        "human_content_relevant": answer.get("content_relevant") or human.get("content_relevant") or "",
        "human_url_relevant": answer.get("url_relevant") or human.get("url_relevant") or "",
        "human_review_status": answer.get("review_status") or human.get("review_status") or "",
        "article_relevance": raw.get("article_relevance") or "",
        "case_nature": redact(str(raw.get("case_nature") or "")),
        "evidence_level": raw.get("evidence_level") or "",
        "incident_outcome": raw.get("incident_outcome") or "",
        "outcome_subject": redact(str(raw.get("outcome_subject") or "")),
        "outcome_notes": redact(str(raw.get("outcome_notes") or "")),
        "scam_type": [redact(str(item)) for item in as_list(raw.get("scam_type"))],
        "scam_tactics": [redact(str(item)) for item in as_list(raw.get("scam_tactics"))],
        "platforms": [redact(str(item)) for item in as_list(raw.get("platforms"))],
        "suspicious_signals": [redact(str(item)) for item in as_list(raw.get("suspicious_signals"))],
        "keywords": [redact(str(item)) for item in as_list(raw.get("keywords"))],
        "victim_situation": redact(str(raw.get("victim_situation") or "")),
        "event_summary": redact(str(raw.get("event_summary") or "")),
        "confidence": raw.get("confidence") or "",
        "analysis_version": raw.get("analysis_version") or "grok_batch_01_analysis_v2",
        "source_type": "ptt_article",
        "sampling_note": SAMPLING_NOTE,
        "exception_flag": review_id == "ptt_1b8bd1aaca02",
        "release_version": RELEASE_VERSION,
        "label_meaning": LABEL_MEANING,
    }
    unknown = set(row) - set(AI_FIELDS)
    if unknown or set(FORBIDDEN_KEYS) & set(row):
        raise RuntimeError(f"ai schema drift: {unknown}")
    return row


def load_ai_jsonl(path: Path | None) -> list[dict]:
    if path is None or not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def csv_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: csv_value(row.get(key)) for key in fields})


def write_datasheet(path: Path, summary: dict) -> None:
    counts = summary["counts"]
    answers_note = (
        f"這次有讀人審快照 `{summary['answers_snapshot']}`，"
        "而且快照裡的 reviewer、human_notes 已在匯出時刪除。"
        if summary["answers_snapshot"]
        else (
            "這次凍結沒有附上 Supabase 人審快照。"
            "因此 review_status 全部是 none，content_relevant 與 stage2_grade 先留空。"
            "線上儀表板仍會即時讀不含審查者姓名與備註的公開欄位；"
            "那不是這份凍結檔的官方筆數。"
        )
    )
    ai_note = (
        f"AI 結構化附錄 {counts['ai_structured_rows']} 列，已刪除 evidence_quotes 與 reasoning。"
        if counts["ai_structured_rows"]
        else "這次倉庫裡沒有 grok_batch_01_analysis_v2.jsonl，所以沒有附上 AI 結構化檔，也不補造 20 篇。"
    )
    text = f"""# 反詐騙專題公開資料集資料卡（{RELEASE_VERSION}）

凍結日期：{summary['frozen_at']}
授權：CC0 1.0 Universal（公有領域貢獻）
標籤意義常數：`{LABEL_MEANING}`

## 這份資料是什麼

這是畢業專題的研究附錄，用來說明我們蒐集到哪些 PTT 文章、它們是否被標成「議題相關」，以及文章裡的網址有沒有出現在一份官方名單快照。

它不是法院認定的詐騙名單，也不是 Spam／Clean 資料集。引用這份資料，不等於引用「已確認詐騙案例」。

## 數字（各列不要加總成確認案例數）

| 清單 | 列數 | 說明 |
|---|---:|---|
| 第一階段 `ptt_candidate` | {counts['stage1_rows']} | 一列一篇審查清單文章 |
| 第二階段 `ptt_stage2_keyword` | {counts['stage2_rows']} | 另一份清單，不是第一階段的子集 |
| 兩份清單網址重疊 | {counts['overlap_urls']} | 重疊文章在兩個 dataset_type 各留一列 |
| 檔案總列數 | {counts['relevance_rows']} | 等於上面兩份列數相加，因為重疊列刻意各留一筆。這不是不重複文章數，也不是確認案例數 |
| 官方名單 exact_match | {counts['official_exact_match_rows']} | 只代表正文網址與官方快照 exact 相同。命中不等於詐騙成立，未命中不等於安全 |
| AI 結構化附錄 | {counts['ai_structured_rows']} | 沒有原文，也沒有 evidence_quotes |
| 群眾自述 RAG 列 | {counts['crowd_rag_rows']} | 這次凍結是 0 列。核准後的群眾自述必須另標「群眾自述（未獨立查證）」，不能併進 PTT 列數 |

{answers_note}

{ai_note}

## 標籤怎麼讀

- `content_relevant`／`url_relevant`：人看過之後，覺得文章或其中網址「跟詐騙議題有沒有關」。yes／no 不是有罪或無罪。
- `stage2_grade`：A 值得保留、B 價值有限、C 無關。這不是 Spam／Clean。
- `evidence_level`：只有 AI 附錄才有。confirmed_case／suspected_case／related_article／cannot_determine。它不能從人審相關性直接推出來。
- `official_match_status`：`exact_match` 是官方 URL 快照 exact 命中；`no_exact_match` 對應內部狀態 `temp`（這份快照沒有 exact 命中）；`not_in_snapshot` 代表該網址不在 article1 狀態檔（狀態檔來自爬蟲 1,175 篇，不是 1,190 全覆蓋）。`official_fuzzy_url_signal` 只是短網址一類的模糊訊號，同樣不是定罪。狀態檔裡若有 exact 命中但不在這兩份審查清單，不會出現在上表，所以表上的 0 不是「整個 PTT 都沒有官方網址命中」。
- `label_meaning` 固定是 `{LABEL_MEANING}`。

## 怎麼蒐集的

第一階段與第二階段清單來自 PTT（主要看板 Bunco、e-shopping、Bank_Service），搜尋詞以詐騙、被騙、匯款這類詞為主。關鍵字搜尋會讓資料偏向「標題或內文已經出現這些詞」的文章。年份大約從 2000 年代到 2026 年，手法新舊混在一起。這次已查的 Dcard 檔是空的，沒有放進公開包。

官方比對用的是專案裡的 `data/review/run_stage1_pipeline/ptt_article1_status.csv`。政府開放資料本身不在這個包裝裡重發。

## 故意沒放的欄位

- PTT 全文與推文（`content`）
- `human_notes`、`reviewer`
- `evidence_quotes`、未處理的 `reasoning`
- 任何 API 金鑰、審查口令、IP

標題、關鍵字與 AI 摘要會先跑電話、市話、身分證、Email、LINE ID、帳號樣式。掃到就遮蔽，並把 `title_redacted` 設為 true。規則擋不住所有中文姓名與間接識別，使用時仍要自己判斷。

## 測試集

主線可信測試集還沒有跟這份 v0.1 一起凍結。`in_trusted_testset` 全部是 false，`split` 全部是 unassigned。之後如果測試集定版，要重跑匯出，不能手改這兩個欄位。

## 授權與引用

本資料集以 CC0 1.0 貢獻到公有領域，任何人可以複製、修改、散布，包含商業使用，不必另外取得許可。詳見同目錄 `LICENSE.md` 與 https://creativecommons.org/publicdomain/zero/1.0/deed.zh-hant

CC0 只涵蓋我們有權釋出的欄位（識別碼、網址、標題、統計、標籤、去識別化摘要）。它不代表我們擁有 PTT 原文，原文本來就沒有放進這個包裝。

```
定偉（2026）。反詐騙專題 PTT 議題相關性資料集（版本 {RELEASE_VERSION}）[資料集]。
https://ccf540123.github.io/anti-scam/#dataset
```

```
Ding-Wei Chen (2026). Anti-scam PTT Topic-Relevance Dataset ({RELEASE_VERSION}) [Data set].
https://ccf540123.github.io/anti-scam/#dataset
```

## 維護

重新產生檔案：

```
python scripts/export_public_dataset.py
```

問題請回到專案儲存庫回報。下一版再用 v0.2，不要覆蓋已經發出的 v0.1 檔名而不改版本號。
"""
    path.write_text(text, encoding="utf-8")


def write_license(path: Path) -> None:
    path.write_text(
        """# CC0 1.0 Universal

本資料集（JSONL、CSV、資料卡與清單）以 Creative Commons CC0 1.0 Universal 釋出。

資料集維護者盡其所知，自願放棄對這些整理後欄位的著作權與相關權利，把它們貢獻到公有領域。你可以複製、修改、散布與商用，不需要另外請求許可。

官方說明：https://creativecommons.org/publicdomain/zero/1.0/deed.zh-hant
法律文本：https://creativecommons.org/publicdomain/zero/1.0/legalcode

這份授權不是犯罪認定，也不包含沒有放進資料集的 PTT 全文。使用資料時請同時閱讀 DATASHEET.md：人審標籤是議題相關性，官方名單命中不等於詐騙成立。
""",
        encoding="utf-8",
    )


def write_citation(path: Path) -> None:
    path.write_text(
        f"""定偉（2026）。反詐騙專題 PTT 議題相關性資料集（版本 {RELEASE_VERSION}）[資料集]。
https://ccf540123.github.io/anti-scam/#dataset

Ding-Wei Chen (2026). Anti-scam PTT Topic-Relevance Dataset ({RELEASE_VERSION}) [Data set].
https://ccf540123.github.io/anti-scam/#dataset

授權：CC0 1.0 Universal
標籤意義：{LABEL_MEANING}
""",
        encoding="utf-8",
    )


def build_rows(stage1_path: Path, stage2_path: Path, official_path: Path, answers_path: Path | None, ai_path: Path | None):
    stage1 = read_csv(stage1_path)
    stage2 = read_csv(stage2_path)
    official = load_official(official_path)
    answers = load_answers(answers_path)
    stage1_urls = {canon_url(row.get("article_url") or "") for row in stage1}
    stage2_urls = {canon_url(row.get("article_url") or "") for row in stage2}
    relevance = []
    analysis1 = []
    analysis2 = []
    for source in stage1:
        if not (source.get("review_id") or "").strip():
            continue
        relevance.append(relevance_row(source, answers, official, stage2_urls, "ptt_candidate"))
        analysis1.append(analysis_row(source, "ptt_candidate"))
    for source in stage2:
        if not (source.get("review_id") or "").strip():
            continue
        relevance.append(
            relevance_row(source, answers, official, stage1_urls, "ptt_stage2_keyword")
        )
        analysis2.append(analysis_row(source, "ptt_stage2_keyword"))
    ai_rows = [public_ai_row(raw, answers) for raw in load_ai_jsonl(ai_path)]
    return relevance, analysis1, analysis2, ai_rows, official


def export_all(
    root: Path = ROOT,
    out_dir: Path | None = None,
    answers_snapshot: Path | None = None,
    ai_jsonl: Path | None = None,
    frozen_at: str = "2026-11-26",
    write_browser_pii: bool | None = None,
) -> dict:
    root = Path(root)
    out_dir = Path(out_dir) if out_dir else root / "docs" / "dataset"
    out_dir.mkdir(parents=True, exist_ok=True)
    stage1_path = root / "docs" / "review" / "items.csv"
    stage2_path = root / "docs" / "review" / "stage2_items.csv"
    official_path = root / "data" / "review" / "run_stage1_pipeline" / "ptt_article1_status.csv"
    if ai_jsonl is None:
        candidate = root / "data" / "grok_batch_01_analysis_v2.jsonl"
        ai_jsonl = candidate if candidate.exists() else None

    relevance, analysis1, analysis2, ai_rows, _official = build_rows(
        stage1_path, stage2_path, official_path, answers_snapshot, ai_jsonl
    )
    stage1_rows = [row for row in relevance if row["dataset_type"] == "ptt_candidate"]
    stage2_rows = [row for row in relevance if row["dataset_type"] == "ptt_stage2_keyword"]
    overlap_urls = sum(1 for row in stage2_rows if row["overlap_with_stage1"])
    exact_rows = sum(1 for row in relevance if row["official_match_status"] == "exact_match")

    write_jsonl(out_dir / "anti_scam_ptt_relevance_v0.jsonl", relevance)
    write_csv(out_dir / "anti_scam_ptt_relevance_v0.csv", relevance, RELEVANCE_FIELDS)
    write_csv(out_dir / "analysis_stage1.csv", analysis1, ANALYSIS_STAGE1_FIELDS)
    write_csv(out_dir / "analysis_stage2.csv", analysis2, ANALYSIS_STAGE2_FIELDS)
    write_csv(out_dir / "user_submission_cases.csv", [], CROWD_RAG_FIELDS)
    if ai_rows:
        write_jsonl(out_dir / "anti_scam_ai_structured_v0.jsonl", ai_rows)
        write_csv(out_dir / "anti_scam_ai_structured_v0.csv", ai_rows, AI_FIELDS)
    else:
        for name in ("anti_scam_ai_structured_v0.jsonl", "anti_scam_ai_structured_v0.csv"):
            stale = out_dir / name
            if stale.exists():
                stale.unlink()

    summary = {
        "frozen_at": frozen_at,
        "answers_snapshot": str(answers_snapshot) if answers_snapshot else None,
        "counts": {
            "stage1_rows": len(stage1_rows),
            "stage2_rows": len(stage2_rows),
            "overlap_urls": overlap_urls,
            "relevance_rows": len(relevance),
            "official_exact_match_rows": exact_rows,
            "ai_structured_rows": len(ai_rows),
            "crowd_rag_rows": 0,
        },
    }
    write_datasheet(out_dir / "DATASHEET.md", summary)
    write_license(out_dir / "LICENSE.md")
    write_citation(out_dir / "CITATION.txt")
    (out_dir / "pii_patterns.json").write_text(
        json.dumps({"rules": list(load_rules())}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if write_browser_pii is None:
        write_browser_pii = out_dir.resolve() == (root / "docs" / "dataset").resolve()
    if write_browser_pii:
        (root / "docs" / "pii.js").write_text(render_browser_script(), encoding="utf-8")

    packaged = [
        "anti_scam_ptt_relevance_v0.jsonl",
        "anti_scam_ptt_relevance_v0.csv",
        "analysis_stage1.csv",
        "analysis_stage2.csv",
        "user_submission_cases.csv",
        "DATASHEET.md",
        "LICENSE.md",
        "CITATION.txt",
        "pii_patterns.json",
    ]
    if ai_rows:
        packaged.extend(
            ["anti_scam_ai_structured_v0.jsonl", "anti_scam_ai_structured_v0.csv"]
        )

    file_info = {}
    sum_lines = []
    for name in packaged:
        path = out_dir / name
        digest = sha256_file(path)
        file_info[name] = {
            "sha256": digest,
            "bytes": path.stat().st_size,
            "rows": _row_count(name, summary, path),
        }
        sum_lines.append(f"{digest}  {name}")
    sums_path = out_dir / "SHA256SUMS"
    sums_path.write_text("\n".join(sum_lines) + "\n", encoding="utf-8")
    sums_digest = sha256_file(sums_path)
    file_info["SHA256SUMS"] = {"sha256": sums_digest, "bytes": sums_path.stat().st_size, "rows": None}

    status_counts = Counter(row["official_match_status"] for row in relevance)
    manifest = {
        "name": "反詐騙專題 PTT 議題相關性資料集",
        "version": RELEASE_VERSION,
        "license": LICENSE_ID,
        "frozen_at": frozen_at,
        "label_meaning": LABEL_MEANING,
        "answers_snapshot": summary["answers_snapshot"],
        "do_not_sum": "stage1_rows 與 stage2_rows 是兩份清單。relevance_rows 含重疊列，不可當成不重複文章數或確認案例數。",
        "counts": summary["counts"],
        "official_match_status_counts": dict(status_counts),
        "excluded_fields": sorted(FORBIDDEN_KEYS),
        "in_trusted_testset": False,
        "crowd_rag_note": "user_submission_cases.csv 目前只有欄位名稱。核准後的列必須帶 source_label「群眾自述（未獨立查證）」，且不得寫回 ptt_scam_cases.csv。",
        "files": file_info,
    }
    (out_dir / "dataset_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _assert_package_safe(out_dir)
    return manifest


def _row_count(name: str, summary: dict, path: Path) -> int | None:
    counts = summary["counts"]
    if name.startswith("anti_scam_ptt_relevance"):
        return counts["relevance_rows"]
    if name.startswith("anti_scam_ai_structured"):
        return counts["ai_structured_rows"]
    if name == "user_submission_cases.csv":
        return 0
    if name == "analysis_stage1.csv":
        return counts["stage1_rows"]
    if name == "analysis_stage2.csv":
        return counts["stage2_rows"]
    return None


def _assert_package_safe(out_dir: Path) -> None:
    for path in out_dir.iterdir():
        if path.suffix not in {".jsonl", ".csv", ".json"}:
            continue
        if path.name == "pii_patterns.json":
            continue
        text = path.read_text(encoding="utf-8-sig")
        for key in ("human_notes", "reviewer", "evidence_quotes"):
            if re.search(rf'"{key}"\s*:', text) or re.search(rf"(?:^|,){key}(?:,|\r?$)", text, re.M):
                raise RuntimeError(f"{path.name} still publishes {key}")


def main() -> None:
    parser = argparse.ArgumentParser(description="匯出 CC0 公開資料集 v0.1")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--answers-snapshot", type=Path, default=None)
    parser.add_argument("--ai-jsonl", type=Path, default=None)
    parser.add_argument("--frozen-at", default="2026-11-26")
    args = parser.parse_args()
    manifest = export_all(
        root=args.root,
        out_dir=args.out_dir,
        answers_snapshot=args.answers_snapshot,
        ai_jsonl=args.ai_jsonl,
        frozen_at=args.frozen_at,
    )
    print(json.dumps(manifest["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
