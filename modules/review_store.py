"""研究小組 Review 資料讀寫（不改動原始研究 CSV schema）。"""

from __future__ import annotations

import csv
import json
import os
import threading
from pathlib import Path

_lock = threading.Lock()

DEFAULT_ITEMS_CSV = os.path.join(
    "data",
    "review",
    "run_20260930_dual_source",
    "176455_fuzzy_manual_review.csv",
)
DEFAULT_ANSWERS_PATH = os.path.join(
    "data",
    "review",
    "run_20260930_dual_source",
    "fuzzy_manual_answers.json",
)
PTT_CASES_CSV = "ptt_scam_cases.csv"

# 與既有人工審查欄位一致
ANSWER_FIELDS = [
    "destination_opened",
    "destination_type",
    "is_scam_related_destination",
    "human_notes",
    "reviewer",
    "review_status",
]


def _project_path(*parts: str) -> Path:
    root = Path(__file__).resolve().parents[1]
    return root.joinpath(*parts)


def items_csv_path() -> Path:
    configured = os.getenv("REVIEW_ITEMS_CSV", DEFAULT_ITEMS_CSV)
    path = Path(configured)
    if not path.is_absolute():
        path = _project_path(configured)
    return path


def answers_path() -> Path:
    configured = os.getenv("REVIEW_ANSWERS_PATH", DEFAULT_ANSWERS_PATH)
    path = Path(configured)
    if not path.is_absolute():
        path = _project_path(configured)
    return path


def load_ptt_content_by_url() -> dict[str, str]:
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


def load_answers() -> dict:
    path = answers_path()
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as file:
        data = json.load(file)
    return data if isinstance(data, dict) else {}


def save_answers(answers: dict) -> None:
    path = answers_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as file:
        json.dump(answers, file, ensure_ascii=False, indent=2)
    tmp.replace(path)


def load_review_items() -> list[dict]:
    path = items_csv_path()
    if not path.exists():
        raise FileNotFoundError(f"找不到 review CSV：{path}")

    content_map = load_ptt_content_by_url()
    with _lock:
        answers = load_answers()

    items: list[dict] = []
    with open(path, encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            review_id = str(row.get("review_id") or "").strip()
            if not review_id:
                continue
            article_url = (row.get("article_url") or "").strip()
            answer = answers.get(review_id) or {}

            # CSV 內若已有人工欄位，作為備援；server answers 優先
            merged = {
                "review_id": int(review_id) if review_id.isdigit() else review_id,
                "shortener_host": row.get("shortener_host") or "",
                "title": row.get("title") or "",
                "article_url": article_url,
                "published_at": row.get("published_at") or "",
                "extracted_url": row.get("extracted_url") or "",
                "normalized_url": row.get("normalized_url") or "",
                "match_reason": row.get("match_reason") or "",
                "content": content_map.get(article_url, ""),
                "destination_opened": answer.get(
                    "destination_opened", row.get("destination_opened") or ""
                ),
                "destination_type": answer.get(
                    "destination_type", row.get("destination_type") or ""
                ),
                "is_scam_related_destination": answer.get(
                    "is_scam_related_destination",
                    row.get("is_scam_related_destination") or "",
                ),
                "human_notes": answer.get("human_notes", row.get("human_notes") or ""),
                "reviewer": answer.get("reviewer", row.get("reviewer") or ""),
                "review_status": answer.get(
                    "review_status", row.get("review_status") or "pending"
                ),
            }
            items.append(merged)

    items.sort(key=lambda item: int(item["review_id"]) if str(item["review_id"]).isdigit() else 0)
    return items


def is_item_filled(item: dict) -> bool:
    return bool(
        (item.get("destination_opened") or "").strip()
        or (item.get("destination_type") or "").strip()
        or (item.get("is_scam_related_destination") or "").strip()
    )


def progress_stats(items: list[dict]) -> dict:
    total = len(items)
    done = sum(1 for item in items if is_item_filled(item))
    return {"total": total, "done": done, "remaining": max(total - done, 0)}


def upsert_answer(review_id: str, payload: dict) -> dict:
    cleaned = {}
    for field in ANSWER_FIELDS:
        if field in payload and payload[field] is not None:
            cleaned[field] = str(payload[field]).strip()

    if not cleaned.get("review_status"):
        if (
            cleaned.get("destination_opened")
            or cleaned.get("destination_type")
            or cleaned.get("is_scam_related_destination")
        ):
            cleaned["review_status"] = "reviewed"
        else:
            cleaned["review_status"] = "pending"

    with _lock:
        answers = load_answers()
        current = dict(answers.get(str(review_id)) or {})
        current.update(cleaned)
        answers[str(review_id)] = current
        save_answers(answers)
        return current
