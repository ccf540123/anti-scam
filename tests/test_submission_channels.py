"""民眾投稿的接觸管道必須前後端同一份，且保留既有值。"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LEGACY_CHANNELS = [
    "電話",
    "簡訊",
    "LINE",
    "Facebook",
    "IG",
    "購物平台",
    "ATM／超商",
    "電子郵件",
    "其他",
]
NEW_CHANNELS = [
    "Threads",
    "抖音 / TikTok",
    "交友 App",
    "賣貨便",
]
# 新選項放在「其他」前面。既有九個值與相對順序保持原樣。
EXPECTED_CHANNELS = LEGACY_CHANNELS[:-1] + NEW_CHANNELS + ["其他"]
MARKER = "ATM／超商"
SKIP_DIRS = {".git", "env", ".venv", "node_modules", "__pycache__", "data"}
SOURCE_SUFFIXES = {".py", ".js", ".ts", ".sql", ".html", ".md"}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _html_channels() -> list[str]:
    html = _read(ROOT / "docs" / "index.html")
    section = re.search(
        r"<legend>接觸管道（可不選）</legend>(.*?)</fieldset>",
        html,
        re.S,
    )
    assert section, "公開投稿頁找不到接觸管道欄位"
    pairs = re.findall(
        r'<input type="checkbox" name="channel" value="([^"]+)">\s*([^<]*)</label>',
        section.group(1),
    )
    assert pairs, "接觸管道沒有核取方塊"
    values = [value for value, _label in pairs]
    labels = [label.strip() for _value, label in pairs]
    assert values == labels
    return values


def _edge_source() -> str:
    return _read(ROOT / "supabase" / "functions" / "submit-scam-experience" / "index.ts")


def _edge_channels() -> list[str]:
    match = re.search(r"const CHANNELS = \[(.*?)\];", _edge_source(), re.S)
    assert match, "Edge Function 找不到 CHANNELS"
    return re.findall(r'"((?:\\.|[^"\\])*)"', match.group(1))


def _filter_like_edge(raw, allowed: list[str]) -> list[str]:
    """對應 index.ts：非陣列變空陣列，不在白名單的值丟掉，不改寫保留下來的字串。"""
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if str(item) in allowed]


def test_form_and_edge_function_use_the_same_channel_list():
    html_channels = _html_channels()
    edge_channels = _edge_channels()
    assert html_channels == EXPECTED_CHANNELS
    assert edge_channels == EXPECTED_CHANNELS
    assert html_channels == edge_channels
    for legacy in LEGACY_CHANNELS:
        assert legacy in edge_channels
    for added in NEW_CHANNELS:
        assert added in edge_channels
    # 全形斜線與空格都是既有或指定字面值，不能換成另一種寫法。
    assert "ATM/超商" not in edge_channels
    assert "抖音/TikTok" not in edge_channels
    assert "交友App" not in edge_channels


def test_edge_function_still_drops_unknown_channels_without_rewriting_known_ones():
    source = _edge_source()
    assert "Array.isArray(body.channels)" in source
    assert "CHANNELS.indexOf(item) >= 0" in source
    allowed = _edge_channels()
    submitted = LEGACY_CHANNELS + NEW_CHANNELS + ["未知管道", "threads", "抖音/TikTok"]
    assert _filter_like_edge(submitted, allowed) == LEGACY_CHANNELS + NEW_CHANNELS
    assert _filter_like_edge(None, allowed) == []
    assert _filter_like_edge("LINE", allowed) == []
    assert _filter_like_edge(["LINE", "LINE", "ATM／超商"], allowed) == [
        "LINE",
        "LINE",
        "ATM／超商",
    ]


def test_original_migration_does_not_constrain_channel_values():
    path = ROOT / "supabase" / "migrations" / "20261126120000_team_review_and_crowd.sql"
    text = _read(path)
    assert "channels jsonb not null default '[]'::jsonb" in text
    assert "scam_submissions_channels_check" not in text
    assert re.search(r"create type\s+\S*channel", text, re.I) is None
    for added in NEW_CHANNELS:
        assert added not in text


def test_later_sql_channel_allowlists_include_legacy_and_new_values():
    old_name = "20261126120000_team_review_and_crowd.sql"
    for path in sorted((ROOT / "supabase").rglob("*.sql")):
        if path.name == old_name:
            continue
        text = _read(path)
        if MARKER not in text and "scam_submissions_channels" not in text:
            continue
        for channel in EXPECTED_CHANNELS:
            assert channel in text, path.name


def test_review_ui_shows_stored_channels_without_a_second_allowlist():
    source = _read(ROOT / "docs" / "review" / "crowd.js")
    assert "function channelsText" in source
    assert 'if (Array.isArray(value)) return value.join("、");' in source
    assert ".select(" in source and "channels" in source
    assert MARKER not in source


def test_public_page_submits_the_checked_values():
    source = _read(ROOT / "docs" / "site.js")
    assert 'input[name="channel"]:checked' in source
    assert "channels: checkedChannels()" in source
    assert MARKER not in source


def test_public_dataset_export_has_no_stale_channel_allowlist():
    source = _read(ROOT / "scripts" / "export_public_dataset.py")
    assert "user_submission_cases.csv" in source
    assert "CROWD_RAG_FIELDS" in source
    # 公開包目前只輸出欄位名稱，沒有另一份接觸管道白名單。platforms 是 AI 自由文字。
    assert MARKER not in source
    assert "Threads" not in source
    for added in NEW_CHANNELS:
        assert added not in source


def test_every_copied_channel_allowlist_includes_the_new_options():
    missing = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.resolve() == Path(__file__).resolve():
            continue
        text = _read(path)
        if MARKER not in text:
            continue
        absent = [channel for channel in EXPECTED_CHANNELS if channel not in text]
        if absent:
            missing.append((str(path.relative_to(ROOT)), absent))
    assert missing == []
