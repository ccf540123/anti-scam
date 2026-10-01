"""
Article 1 研究狀態（第一階段）。

自動 URL 比對只會產生：
  - exact_match：正文 URL 與官方資料有 exact match
  - temp：尚無 exact match，等待後續人工檢查

non_match 僅保留給「人工檢查後確認無用」時使用，不可由自動 cross-reference 產生。

Fuzzy（短網址等）是另一條研究流程，不等於 temp / non_match。
"""

from __future__ import annotations

ARTICLE1_STATUS_TEMP = "temp"
ARTICLE1_STATUS_EXACT_MATCH = "exact_match"
ARTICLE1_STATUS_NON_MATCH = "non_match"  # 僅人工後可用；自動流程不寫入

ARTICLE1_AUTO_STATUSES = (
    ARTICLE1_STATUS_TEMP,
    ARTICLE1_STATUS_EXACT_MATCH,
)


def classify_article1_status(*, has_exact_url_match: bool) -> str:
    """
    第一階段自動狀態：
      has exact official URL match → exact_match
      otherwise → temp
    """
    if has_exact_url_match:
        return ARTICLE1_STATUS_EXACT_MATCH
    return ARTICLE1_STATUS_TEMP


def is_auto_article1_status(status: str) -> bool:
    return (status or "").strip() in ARTICLE1_AUTO_STATUSES
