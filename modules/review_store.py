"""研究小組 Review 資料讀寫（不改動原始研究 CSV / Fuzzy 資料）。"""

from __future__ import annotations

import csv
import json
import os
import threading
from pathlib import Path

_lock = threading.Lock()

DEFAULT_FUZZY_ITEMS_CSV = os.path.join(
    "data",
    "review",
    "run_20260930_dual_source",
    "176455_fuzzy_manual_review.csv",
)
DEFAULT_FUZZY_ANSWERS_PATH = os.path.join(
    "data",
    "review",
    "run_20260930_dual_source",
    "fuzzy_manual_answers.json",
)
DEFAULT_PTT_ITEMS_CSV = os.path.join("data", "review", "ptt_candidates", "items.csv")
DEFAULT_PTT_ANSWERS_PATH = os.path.join(
    "data", "review", "ptt_candidates", "answers.json"
)
PTT_CASES_CSV = "ptt_scam_cases.csv"

# 向後相容：舊環境變數仍對應 Fuzzy dataset
DEFAULT_ITEMS_CSV = DEFAULT_FUZZY_ITEMS_CSV
DEFAULT_ANSWERS_PATH = DEFAULT_FUZZY_ANSWERS_PATH

# Fuzzy：短網址目的地標註
FUZZY_ANSWER_FIELDS = [
    "destination_opened",
    "destination_type",
    "is_scam_related_destination",
    "human_notes",
    "reviewer",
    "review_status",
]

# PTT 候選文章：文章類型標註
PTT_ANSWER_FIELDS = [
    "article_type",
    "human_notes",
    "reviewer",
    "review_status",
]

# 舊名稱相容
ANSWER_FIELDS = FUZZY_ANSWER_FIELDS

DATASETS = {
    "fuzzy": {
        "id": "fuzzy",
        "label": "Fuzzy 候選文章",
        "kind": "fuzzy",
        "description": "既有 Fuzzy／短網址候選，標註目的地",
        "default_items_csv": DEFAULT_FUZZY_ITEMS_CSV,
        "default_answers_path": DEFAULT_FUZZY_ANSWERS_PATH,
        "items_env": "REVIEW_ITEMS_CSV",
        "answers_env": "REVIEW_ANSWERS_PATH",
        "answer_fields": FUZZY_ANSWER_FIELDS,
        "export_filename": "176455_fuzzy_manual_review.csv",
        "export_fields": [
            "review_id",
            "shortener_host",
            "title",
            "article_url",
            "published_at",
            "extracted_url",
            "normalized_url",
            "match_reason",
            "review_status",
            "destination_opened",
            "destination_type",
            "is_scam_related_destination",
            "human_notes",
            "reviewer",
        ],
    },
    "ptt_candidate": {
        "id": "ptt_candidate",
        "label": "PTT 候選文章",
        "kind": "ptt_candidate",
        "description": "PTT crawler 匯入的候選文章，標註文章類型",
        "default_items_csv": DEFAULT_PTT_ITEMS_CSV,
        "default_answers_path": DEFAULT_PTT_ANSWERS_PATH,
        "items_env": "REVIEW_PTT_ITEMS_CSV",
        "answers_env": "REVIEW_PTT_ANSWERS_PATH",
        "answer_fields": PTT_ANSWER_FIELDS,
        "export_filename": "ptt_candidates_manual_review.csv",
        "export_fields": [
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
            "article_type",
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
    key = (dataset_id or "fuzzy").strip() or "fuzzy"
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


def load_ptt_content_by_url() -> dict[str, str]:
    """Fuzzy review 備援：從 RAG 用 CSV 對正文（不修改該檔）。"""
    path = _project_path(PTT_CASES_CSV)
    mapping: dict[str, str] = {}
    if not path.exists():
        return mapping
    with open(path, encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            url = (row.get("url") or "").strip()
            if url and url not in mapping:
                mapping[url] = row.get("content") or ""
    return mapping


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
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as file:
        json.dump(answers, file, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _merge_answer_fields(row: dict, answer: dict, fields: list[str]) -> dict:
    merged = {}
    for field in fields:
        default = "pending" if field == "review_status" else ""
        merged[field] = answer.get(field, row.get(field) or default)
    return merged


def _load_fuzzy_items(path: Path, answers: dict) -> list[dict]:
    content_map = load_ptt_content_by_url()
    items: list[dict] = []
    with open(path, encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            review_id = str(row.get("review_id") or "").strip()
            if not review_id:
                continue
            article_url = (row.get("article_url") or "").strip()
            answer = answers.get(review_id) or {}
            fields = _merge_answer_fields(row, answer, FUZZY_ANSWER_FIELDS)
            items.append(
                {
                    "review_id": int(review_id) if review_id.isdigit() else review_id,
                    "dataset_id": "fuzzy",
                    "dataset_type": "fuzzy",
                    "shortener_host": row.get("shortener_host") or "",
                    "title": row.get("title") or "",
                    "article_url": article_url,
                    "published_at": row.get("published_at") or "",
                    "extracted_url": row.get("extracted_url") or "",
                    "normalized_url": row.get("normalized_url") or "",
                    "match_reason": row.get("match_reason") or "",
                    "content": content_map.get(article_url, ""),
                    "source_board": "",
                    "search_keyword": "",
                    "article_type": "",
                    **fields,
                }
            )
    items.sort(
        key=lambda item: int(item["review_id"])
        if str(item["review_id"]).isdigit()
        else 0
    )
    return items


def _load_ptt_candidate_items(path: Path, answers: dict) -> list[dict]:
    items: list[dict] = []
    with open(path, encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            review_id = str(row.get("review_id") or "").strip()
            if not review_id:
                continue
            answer = answers.get(review_id) or {}
            fields = _merge_answer_fields(row, answer, PTT_ANSWER_FIELDS)
            items.append(
                {
                    "review_id": review_id,
                    "dataset_id": "ptt_candidate",
                    "dataset_type": row.get("dataset_type") or "ptt_candidate",
                    "dedup_key": row.get("dedup_key") or "",
                    "title": row.get("title") or "",
                    "article_url": (row.get("article_url") or "").strip(),
                    "content": row.get("content") or "",
                    "published_at": row.get("published_at") or "",
                    "source": row.get("source") or "ptt",
                    "source_board": row.get("source_board") or "",
                    "search_keyword": row.get("search_keyword") or "",
                    "imported_at": row.get("imported_at") or "",
                    "shortener_host": "",
                    "extracted_url": "",
                    "normalized_url": "",
                    "match_reason": "",
                    "destination_opened": "",
                    "destination_type": "",
                    "is_scam_related_destination": "",
                    **fields,
                }
            )
    items.sort(key=lambda item: str(item["review_id"]))
    return items


def load_review_items(dataset_id: str | None = None) -> list[dict]:
    dataset = get_dataset(dataset_id)
    path = items_csv_path(dataset["id"])
    if not path.exists():
        if dataset["id"] == "ptt_candidate":
            # 尚未匯入時回空清單，讓 UI 提示執行 import
            return []
        raise FileNotFoundError(f"找不到 review CSV：{path}")

    with _lock:
        answers = load_answers(dataset["id"])

    if dataset["kind"] == "ptt_candidate":
        return _load_ptt_candidate_items(path, answers)
    return _load_fuzzy_items(path, answers)


def is_item_filled(item: dict, dataset_id: str | None = None) -> bool:
    kind = (dataset_id or item.get("dataset_id") or item.get("dataset_type") or "fuzzy")
    if kind == "ptt_candidate":
        return bool((item.get("article_type") or "").strip())
    return bool(
        (item.get("destination_opened") or "").strip()
        or (item.get("destination_type") or "").strip()
        or (item.get("is_scam_related_destination") or "").strip()
    )


def progress_stats(items: list[dict], dataset_id: str | None = None) -> dict:
    total = len(items)
    done = sum(1 for item in items if is_item_filled(item, dataset_id))
    return {"total": total, "done": done, "remaining": max(total - done, 0)}


def upsert_answer(
    review_id: str, payload: dict, dataset_id: str | None = None
) -> dict:
    dataset = get_dataset(dataset_id)
    fields = dataset["answer_fields"]
    cleaned = {}
    for field in fields:
        if field in payload and payload[field] is not None:
            cleaned[field] = str(payload[field]).strip()

    if not cleaned.get("review_status"):
        if dataset["kind"] == "ptt_candidate":
            cleaned["review_status"] = (
                "reviewed" if cleaned.get("article_type") else "pending"
            )
        elif (
            cleaned.get("destination_opened")
            or cleaned.get("destination_type")
            or cleaned.get("is_scam_related_destination")
        ):
            cleaned["review_status"] = "reviewed"
        else:
            cleaned["review_status"] = "pending"

    with _lock:
        answers = load_answers(dataset["id"])
        current = dict(answers.get(str(review_id)) or {})
        current.update(cleaned)
        answers[str(review_id)] = current
        save_answers(answers, dataset["id"])
        return current
