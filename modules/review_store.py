"""研究小組 Review 資料讀寫（PTT Temp 人工 Keyword 審查）。

items.csv：GitHub / Render 提供候選文章
answers：正式環境寫入 Supabase；未設定時本機可用檔案後備（僅開發／測試）
"""

from __future__ import annotations

import csv
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from modules import review_answers_store

_lock = threading.Lock()


class ReviewLockedError(Exception):
    """這篇文章已由組員完成審查，不可再覆寫。"""


DEFAULT_PTT_ITEMS_CSV = os.path.join("data", "review", "ptt_candidates", "items.csv")
DEFAULT_PTT_ANSWERS_PATH = os.path.join(
    "data", "review", "ptt_candidates", "answers.json"
)

# 向後相容別名
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


def answers_storage_backend() -> str:
    return "supabase" if review_answers_store.supabase_configured() else "local_file"


def list_datasets() -> list[dict]:
    result = []
    for dataset in DATASETS.values():
        items_path = items_csv_path(dataset["id"])
        result.append(
            {
                "id": dataset["id"],
                "label": dataset["label"],
                "kind": dataset["kind"],
                "description": dataset["description"],
                "has_items": items_path.exists(),
                "items_path": str(items_path),
                "answers_backend": answers_storage_backend(),
            }
        )
    return result


def items_csv_path(dataset_id: str | None = None) -> Path:
    dataset = get_dataset(dataset_id)
    configured = os.getenv(dataset["items_env"], dataset["default_items_csv"])
    return _resolve_path(configured)


def answers_path(dataset_id: str | None = None) -> Path:
    """本機檔案後備路徑（僅未設定 Supabase 時使用）。"""
    dataset = get_dataset(dataset_id)
    configured = os.getenv(dataset["answers_env"], dataset["default_answers_path"])
    return _resolve_path(configured)


def load_answers(dataset_id: str | None = None) -> dict:
    dataset = get_dataset(dataset_id)
    if review_answers_store.supabase_configured():
        return review_answers_store.fetch_all_answers(dataset["id"])
    return review_answers_store.load_answers_from_file(answers_path(dataset["id"]))


def load_one_answer(review_id: str, dataset_id: str | None = None) -> dict:
    dataset = get_dataset(dataset_id)
    if review_answers_store.supabase_configured():
        row = review_answers_store.fetch_one_answer(str(review_id), dataset["id"])
        return row or {}
    answers = review_answers_store.load_answers_from_file(answers_path(dataset["id"]))
    return dict(answers.get(str(review_id)) or {})


def is_review_locked(answer: dict) -> bool:
    """已完成審查的答案不可被其他組員覆寫。"""
    if not answer:
        return False
    if (answer.get("review_status") or "").strip() != "reviewed":
        return False
    return is_ptt_temp_review_complete(answer)


def normalize_keywords(value) -> list[str]:
    """把人工輸入的 keywords 正規成去空白、去空列的 list（不自動抽詞）。"""
    if value is None:
        return []
    if isinstance(value, list):
        raw_parts = [str(item) for item in value]
    else:
        text = str(value).replace("\r\n", "\n").replace("\r", "\n")
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
      - 有任何手動 Keyword → 一律 temp
      - 內容無相關 + URL 無相關/無連結 + 沒有 Keyword → non_match
      - 其餘 → temp
    """
    cr = (content_relevant or "").strip()
    ur = (url_relevant or "").strip()
    if keywords:
        return "temp"
    if cr == "no" and ur in {"no", "none"}:
        return "non_match"
    return "temp"


def is_ptt_temp_review_complete(item: dict) -> bool:
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
                    "saved_at": answer.get("saved_at") or "",
                    "review_locked": is_review_locked(fields),
                    **fields,
                }
            )
    items.sort(key=lambda item: str(item["review_id"]))
    return items


def load_review_items(dataset_id: str | None = None) -> list[dict]:
    dataset = get_dataset(dataset_id)
    path = items_csv_path(dataset["id"])
    if not path.exists():
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
    if keywords is not None:
        cleaned["status"] = derive_ptt_article_status(
            content_relevant=content_relevant or "",
            url_relevant=url_relevant or "",
            keywords=keywords,
        )

    with _lock:
        current = load_one_answer(str(review_id), dataset["id"])
        if is_review_locked(current):
            raise ReviewLockedError(
                f"review_id={review_id} 已完成，請改審其他文章。"
            )
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
        saved_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        current["saved_at"] = saved_at

        if review_answers_store.supabase_configured():
            return review_answers_store.upsert_one_answer(
                str(review_id), current, dataset["id"]
            )

        # 本機／測試後備：寫入檔案（不進 Git，非正式來源）
        path = answers_path(dataset["id"])
        answers = review_answers_store.load_answers_from_file(path)
        answers[str(review_id)] = current
        review_answers_store.save_answers_to_file(answers, path)
        return current
