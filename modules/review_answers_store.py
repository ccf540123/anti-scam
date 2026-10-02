"""
PTT Review answers 永久儲存（Supabase PostgREST）。

正式環境：設 SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY（或 SUPABASE_KEY）
本機／單元測試：未設定時仍可用本機 answers.json（不進 Git）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests

TABLE_NAME = "ptt_review_answers"
DEFAULT_DATASET = "ptt_candidate"


class ReviewAnswersBackendError(RuntimeError):
    """Supabase 讀寫失敗。"""


def supabase_configured() -> bool:
    return bool(os.getenv("SUPABASE_URL", "").strip() and _supabase_key())


def _supabase_key() -> str:
    return (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        or os.getenv("SUPABASE_KEY", "").strip()
    )


def _rest_base() -> str:
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    if not url:
        raise ReviewAnswersBackendError("未設定 SUPABASE_URL")
    return f"{url}/rest/v1"


def _headers(*, prefer: str | None = None) -> dict[str, str]:
    key = _supabase_key()
    if not key:
        raise ReviewAnswersBackendError(
            "未設定 SUPABASE_SERVICE_ROLE_KEY（或 SUPABASE_KEY）"
        )
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def _row_to_answer(row: dict[str, Any]) -> dict[str, Any]:
    keywords = row.get("keywords")
    if isinstance(keywords, str):
        try:
            keywords = json.loads(keywords)
        except json.JSONDecodeError:
            keywords = [keywords] if keywords.strip() else []
    if keywords is None:
        keywords = []
    saved_at = row.get("saved_at") or ""
    if hasattr(saved_at, "isoformat"):
        saved_at = saved_at.isoformat()
    return {
        "content_relevant": row.get("content_relevant") or "",
        "url_relevant": row.get("url_relevant") or "",
        "keywords": keywords if isinstance(keywords, list) else [],
        "status": row.get("status") or "temp",
        "human_notes": row.get("human_notes") or "",
        "reviewer": row.get("reviewer") or "",
        "review_status": row.get("review_status") or "pending",
        "article_type": row.get("article_type") or "",
        "saved_at": str(saved_at),
    }


def _answer_to_row(review_id: str, answer: dict[str, Any], dataset_id: str) -> dict[str, Any]:
    keywords = answer.get("keywords") or []
    if not isinstance(keywords, list):
        keywords = []
    return {
        "review_id": str(review_id),
        "dataset_id": dataset_id or DEFAULT_DATASET,
        "content_relevant": answer.get("content_relevant") or "",
        "url_relevant": answer.get("url_relevant") or "",
        "keywords": keywords,
        "status": answer.get("status") or "temp",
        "human_notes": answer.get("human_notes") or "",
        "reviewer": answer.get("reviewer") or "",
        "review_status": answer.get("review_status") or "pending",
        "article_type": answer.get("article_type") or "",
        "saved_at": answer.get("saved_at") or None,
    }


def fetch_all_answers(dataset_id: str = DEFAULT_DATASET) -> dict[str, dict]:
    """從 Supabase 讀取該 dataset 全部 answers。"""
    params = {
        "select": "*",
        "dataset_id": f"eq.{dataset_id}",
    }
    response = requests.get(
        f"{_rest_base()}/{TABLE_NAME}",
        headers=_headers(),
        params=params,
        timeout=30,
    )
    if response.status_code >= 400:
        raise ReviewAnswersBackendError(
            f"Supabase 讀取失敗 HTTP {response.status_code}: {response.text[:300]}"
        )
    rows = response.json()
    if not isinstance(rows, list):
        raise ReviewAnswersBackendError("Supabase 回傳格式異常")
    result: dict[str, dict] = {}
    for row in rows:
        rid = str(row.get("review_id") or "").strip()
        if rid:
            result[rid] = _row_to_answer(row)
    return result


def fetch_one_answer(
    review_id: str, dataset_id: str = DEFAULT_DATASET
) -> dict | None:
    params = {
        "select": "*",
        "review_id": f"eq.{review_id}",
        "dataset_id": f"eq.{dataset_id}",
        "limit": "1",
    }
    response = requests.get(
        f"{_rest_base()}/{TABLE_NAME}",
        headers=_headers(),
        params=params,
        timeout=30,
    )
    if response.status_code >= 400:
        raise ReviewAnswersBackendError(
            f"Supabase 讀取失敗 HTTP {response.status_code}: {response.text[:300]}"
        )
    rows = response.json()
    if not rows:
        return None
    return _row_to_answer(rows[0])


def upsert_one_answer(
    review_id: str, answer: dict[str, Any], dataset_id: str = DEFAULT_DATASET
) -> dict:
    """寫入／更新一筆 answer（on conflict review_id）。"""
    payload = _answer_to_row(review_id, answer, dataset_id)
    response = requests.post(
        f"{_rest_base()}/{TABLE_NAME}",
        headers=_headers(prefer="resolution=merge-duplicates,return=representation"),
        params={"on_conflict": "review_id"},
        json=payload,
        timeout=30,
    )
    if response.status_code >= 400:
        raise ReviewAnswersBackendError(
            f"Supabase 寫入失敗 HTTP {response.status_code}: {response.text[:300]}"
        )
    rows = response.json()
    if isinstance(rows, list) and rows:
        return _row_to_answer(rows[0])
    return dict(answer)


# ---------------------------------------------------------------------------
# 本機檔案後備（僅單元測試／未設 Supabase 時）
# ---------------------------------------------------------------------------


def load_answers_from_file(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as file:
        data = json.load(file)
    return data if isinstance(data, dict) else {}


def save_answers_to_file(answers: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as file:
        json.dump(answers, file, ensure_ascii=False, indent=2)
        file.flush()
        os.fsync(file.fileno())
    tmp.replace(path)
