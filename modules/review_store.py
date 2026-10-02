"""研究小組 Review 資料讀寫（PTT Temp 人工 Keyword 審查）。"""

from __future__ import annotations

import csv
import json
import os
import threading
from pathlib import Path

_lock = threading.Lock()

DEFAULT_PTT_ITEMS_CSV = os.path.join("data", "review", "ptt_candidates", "items.csv")
DEFAULT_PTT_ANSWERS_PATH = os.path.join(
    "data", "review", "ptt_candidates", "answers.json"
)

# 向後相容別名：舊環境變數若仍指向 Fuzzy，改以 PTT 為正式預設
DEFAULT_ITEMS_CSV = DEFAULT_PTT_ITEMS_CSV
DEFAULT_ANSWERS_PATH = DEFAULT_PTT_ANSWERS_PATH

# PTT Temp 候選：人工相關性 + 手動多 Keyword
PTT_ANSWER_FIELDS = [
    "content_relevant",
    "url_relevant",
    "keywords",
    "status",
    "human_notes",
    "reviewer",
    "review_status",
    # 舊欄位保留讀取相容，不再作為主要標註
    "article_type",
]

ANSWER_FIELDS = PTT_ANSWER_FIELDS

DATASETS = {
    "ptt_candidate": {
        "id": "ptt_candidate",
        "label": "PTT Temp 候選",
        "kind": "ptt_candidate",
        "description": "第一階段 Temp Article 1：人工檢查並手動輸入多個 Keyword",
        "default_items_csv": DEFAULT_PTT_ITEMS_CSV,
        "default_answers_path": DEFAULT_PTT_ANSWERS_PATH,
        "items_env": "REVIEW_PTT_ITEMS_CSV",
        "answers_env": "REVIEW_PTT_ANSWERS_PATH",
        "answer_fields": PTT_ANSWER_FIELDS,
        "export_filename": "ptt_temp_manual_review.csv",
        "export_fields": [
            "article_id",
            "review_id",
            "title",
            "article_url",
            "url",
            "published_at",
            "source",
            "source_board",
            "search_keyword",
            "content_relevant",
            "url_relevant",
            "keywords",
            "status",
            "review_status",
            "human_notes",
            "reviewer",
        ],
    },
}


def _project_path(*parts: str) -> Path:
    root = Path(__file__).resolve().parents[1]
    return root.joinpath(*parts)


def _resolve_path(configured: str) -> Path:
    path = Path(configured)
    if not path.is_absolute():
        path = _project_path(configured)
    return path


def get_dataset(dataset_id: str | None = None) -> dict:
    key = (dataset_id or "ptt_candidate").strip() or "ptt_candidate"
    if key not in DATASETS:
        raise KeyError(f"未知 dataset：{key}")
    return DATASETS[key]


def list_datasets() -> list[dict]:
    result = []
    for dataset in DATASETS.values():
        items_path = items_csv_path(dataset["id"])
        answers = answers_path(dataset["id"])
        result.append(
            {
                "id": dataset["id"],
                "label": dataset["label"],
                "kind": dataset["kind"],
                "description": dataset["description"],
                "has_items": items_path.exists(),
                "items_path": str(items_path),
                "answers_path": str(answers),
            }
        )
    return result


def items_csv_path(dataset_id: str | None = None) -> Path:
    dataset = get_dataset(dataset_id)
    configured = os.getenv(dataset["items_env"], dataset["default_items_csv"])
    return _resolve_path(configured)


def answers_path(dataset_id: str | None = None) -> Path:
    dataset = get_dataset(dataset_id)
    configured = os.getenv(dataset["answers_env"], dataset["default_answers_path"])
    return _resolve_path(configured)


def load_answers(dataset_id: str | None = None) -> dict:
    path = answers_path(dataset_id)
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as file:
        data = json.load(file)
    return data if isinstance(data, dict) else {}


def save_answers(answers: dict, dataset_id: str | None = None) -> None:
    path = answers_path(dataset_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as file:
        json.dump(answers, file, ensure_ascii=False, indent=2)
    tmp.replace(path)


def normalize_keywords(value) -> list[str]:
    """把人工輸入的 keywords 正規成去空白、去空列的 list（不自動抽詞）。"""
    if value is None:
        return []
    if isinstance(value, list):
        raw_parts = [str(item) for item in value]
    else:
        text = str(value).replace("\r\n", "\n").replace("\r", "\n")
        # 相容：一行一個，或 | / 、 分隔
        text = text.replace("|", "\n").replace("、", "\n")
        raw_parts = text.split("\n")
    cleaned: list[str] = []
    seen: set[str] = set()
    for part in raw_parts:
        keyword = part.strip()
        if not keyword or keyword in seen:
            continue
        seen.add(keyword)
        cleaned.append(keyword)
    return cleaned


def keywords_to_export_text(keywords: list[str]) -> str:
    return " | ".join(keywords)


def derive_ptt_article_status(
    *,
    content_relevant: str,
    url_relevant: str,
    keywords: list[str],
) -> str:
    """
    人工 Review 後的 Article 1 狀態：
      - 有任何手動 Keyword → 一律 temp（代表仍有後續研究價值）
      - 內容無相關 + URL 無相關/無連結 + 沒有 Keyword → non_match
      - 其餘（尚未完成或未確認）→ temp
    Keyword 只來自組員人工輸入；此函式不抽詞、不推薦。
    """
    cr = (content_relevant or "").strip()
    ur = (url_relevant or "").strip()
    if keywords:
        return "temp"
    if cr == "no" and ur in {"no", "none"}:
        return "non_match"
    return "temp"


def is_ptt_temp_review_complete(item: dict) -> bool:
    """
    Temp Review 完成條件：
      - 已選 content_relevant 與 url_relevant
      - 若任一為「有」→ 必須手動填至少一個 Keyword
      - 若兩者皆無相關：可完成；此時若有 Keyword，status 仍為 temp，
        只有完全沒有 Keyword 才會是 non_match
    """
    cr = (item.get("content_relevant") or "").strip()
    ur = (item.get("url_relevant") or "").strip()
    if not cr or not ur:
        return False
    keywords = normalize_keywords(item.get("keywords"))
    if cr == "yes" or ur == "yes":
        return bool(keywords)
    return True


def _merge_answer_fields(row: dict, answer: dict, fields: list[str]) -> dict:
    merged = {}
    for field in fields:
        if field == "keywords":
            raw = answer.get("keywords", row.get("keywords"))
            merged["keywords"] = normalize_keywords(raw)
            continue
        default = "pending" if field == "review_status" else ""
        if field == "status":
            default = "temp"
        merged[field] = answer.get(field, row.get(field) or default)
    return merged


def _load_ptt_candidate_items(path: Path, answers: dict) -> list[dict]:
    items: list[dict] = []
    with open(path, encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            review_id = str(row.get("review_id") or "").strip()
            if not review_id:
                continue
            # Article 1 / source CSV 的 exact_match 永遠不進 Temp Review。
            # 必須以原始列為準，不可被 answers 舊資料覆寫成 temp。
            source_status = (row.get("status") or "temp").strip()
            if source_status == "exact_match":
                continue
            answer = answers.get(review_id) or {}
            fields = _merge_answer_fields(row, answer, PTT_ANSWER_FIELDS)
            article_url = (row.get("article_url") or "").strip()
            items.append(
                {
                    "review_id": review_id,
                    "article_id": review_id,
                    "dataset_id": "ptt_candidate",
                    "dataset_type": row.get("dataset_type") or "ptt_candidate",
                    "dedup_key": row.get("dedup_key") or "",
                    "title": row.get("title") or "",
                    "article_url": article_url,
                    "url": article_url,
                    "content": row.get("content") or "",
                    "published_at": row.get("published_at") or "",
                    "source": row.get("source") or "ptt",
                    "source_board": row.get("source_board") or "",
                    "search_keyword": row.get("search_keyword") or "",
                    "imported_at": row.get("imported_at") or "",
                    **fields,
                }
            )
    items.sort(key=lambda item: str(item["review_id"]))
    return items


def load_review_items(dataset_id: str | None = None) -> list[dict]:
    dataset = get_dataset(dataset_id)
    path = items_csv_path(dataset["id"])
    if not path.exists():
        # 尚未匯入時回空清單，讓 UI 提示執行 import / pipeline
        return []

    with _lock:
        answers = load_answers(dataset["id"])

    return _load_ptt_candidate_items(path, answers)


def is_item_filled(item: dict, dataset_id: str | None = None) -> bool:
    return is_ptt_temp_review_complete(item)


def progress_stats(items: list[dict], dataset_id: str | None = None) -> dict:
    total = len(items)
    done = sum(1 for item in items if is_item_filled(item, dataset_id))
    return {"total": total, "done": done, "remaining": max(total - done, 0)}


def export_item_row(item: dict, dataset_id: str | None = None) -> dict:
    """匯出用列：keywords 轉成可讀字串。"""
    row = dict(item)
    keywords = normalize_keywords(row.get("keywords"))
    row["keywords"] = keywords_to_export_text(keywords)
    row["article_id"] = row.get("article_id") or row.get("review_id")
    row["url"] = row.get("url") or row.get("article_url") or ""
    return row


def upsert_answer(
    review_id: str, payload: dict, dataset_id: str | None = None
) -> dict:
    dataset = get_dataset(dataset_id)
    fields = dataset["answer_fields"]
    cleaned = {}

    for field in fields:
        if field not in payload or payload[field] is None:
            continue
        if field == "keywords":
            cleaned["keywords"] = normalize_keywords(payload[field])
        else:
            cleaned[field] = str(payload[field]).strip()

    content_relevant = cleaned.get("content_relevant", "")
    url_relevant = cleaned.get("url_relevant", "")
    keywords = cleaned.get("keywords")
    if keywords is None:
        keywords = None
    else:
        cleaned["status"] = derive_ptt_article_status(
            content_relevant=content_relevant or "",
            url_relevant=url_relevant or "",
            keywords=keywords,
        )

    with _lock:
        answers = load_answers(dataset["id"])
        current = dict(answers.get(str(review_id)) or {})
        if "keywords" not in cleaned and "keywords" in current:
            keywords = normalize_keywords(current.get("keywords"))
        elif keywords is None:
            keywords = normalize_keywords(current.get("keywords"))
        else:
            keywords = cleaned["keywords"]

        merged_content = cleaned.get(
            "content_relevant", current.get("content_relevant", "")
        )
        merged_url = cleaned.get("url_relevant", current.get("url_relevant", ""))
        cleaned["keywords"] = keywords
        cleaned["status"] = derive_ptt_article_status(
            content_relevant=str(merged_content or ""),
            url_relevant=str(merged_url or ""),
            keywords=keywords,
        )

        probe = {
            "content_relevant": merged_content,
            "url_relevant": merged_url,
            "keywords": keywords,
        }
        if not cleaned.get("review_status"):
            cleaned["review_status"] = (
                "reviewed" if is_ptt_temp_review_complete(probe) else "pending"
            )

        current.update(cleaned)
        answers[str(review_id)] = current
        save_answers(answers, dataset["id"])
        return current
