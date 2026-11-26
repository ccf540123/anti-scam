"""公開資料集匯出、去識別化與 manifest 完整性。"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.export_public_dataset import (  # noqa: E402
    FORBIDDEN_KEYS,
    export_all,
)
from scripts.pii_patterns import redact, render_browser_script  # noqa: E402


PII_CASES = [
    ("請打 0912-345-678", "0912345678", "[PHONE]"),
    ("手機 0912345678 謝謝", "0912345678", "[PHONE]"),
    ("市話 (02)2345-6789", "2345-6789", "[PHONE]"),
    ("公司電話 03-1234567", "03-1234567", "[PHONE]"),
    ("身分證 A123456789", "A123456789", "[NATIONAL_ID]"),
    ("信箱 ada@example.com", "ada@example.com", "[EMAIL]"),
    ("我的 LINE ID: cool_cat", "cool_cat", "[CHAT_ID]"),
    ("匯款帳號 1234567890123", "1234567890123", "[ACCOUNT]"),
    ("卡號 4242424242424242", "4242424242424242", "[ACCOUNT]"),
    ("我叫王小明，請匯款", "王小明", "[NAME]"),
    ("連結 https://example.com/path?token=abc&email=a@b.com", "token=abc", "https://example.com/path"),
    ("加我 https://line.me/R/ti/p/~secret", "secret", "[CHAT_ID]"),
]


def test_redacts_taiwan_pii_patterns():
    for original, secret, marker in PII_CASES:
        cleaned = redact(original)
        assert secret not in cleaned, (original, cleaned)
        assert marker in cleaned, (original, cleaned)


def test_browser_script_matches_python_redaction(tmp_path):
    script = tmp_path / "pii.js"
    script.write_text(render_browser_script(), encoding="utf-8")
    node = subprocess.run(
        [
            "node",
            "-e",
            (
                "const pii=require(process.argv[1]);"
                "const cases=JSON.parse(process.argv[2]);"
                "const out=cases.map((row)=>pii.redact(row));"
                "process.stdout.write(JSON.stringify(out));"
            ),
            str(script),
            json.dumps([row[0] for row in PII_CASES], ensure_ascii=False),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    browser_rows = json.loads(node.stdout)
    python_rows = [redact(row[0]) for row in PII_CASES]
    assert browser_rows == python_rows


def _write_items(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_export_excludes_private_fields_and_checks_sha256(tmp_path):
    root = tmp_path / "proj"
    review = root / "docs" / "review"
    data_dir = root / "data" / "review" / "run_stage1_pipeline"
    review.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    (root / "docs").mkdir(exist_ok=True)
    fields = [
        "review_id",
        "dataset_type",
        "title",
        "article_url",
        "content",
        "published_at",
        "source",
        "source_board",
        "search_keyword",
        "imported_at",
        "human_notes",
        "reviewer",
    ]
    secret_sentence = "這段全文只有內部檔才有，公開包不可以出現這句話。"
    stage1 = []
    for index in range(3):
        stage1.append(
            {
                "review_id": f"ptt_test_{index}",
                "dataset_type": "ptt_candidate",
                "title": "標題 0912-000-000" if index == 0 else f"標題 {index}",
                "article_url": f"https://www.ptt.cc/bbs/Bunco/M.{index}.html",
                "content": secret_sentence + f" 內文 {index} LINE ID: hidden_one",
                "published_at": "Mon Jan 1 00:00:00 2020",
                "source": "ptt",
                "source_board": "Bunco",
                "search_keyword": "詐騙",
                "imported_at": "2026-11-26",
                "human_notes": "審查者私下記號",
                "reviewer": "alice",
            }
        )
    stage2 = [
        {
            "review_id": "ptt2_overlap",
            "dataset_type": "ptt_stage2_keyword",
            "title": "重疊",
            "article_url": "https://www.ptt.cc/bbs/Bunco/M.0.html",
            "content": secret_sentence + " 第二階段",
            "published_at": "2024-05-01",
            "source": "ptt",
            "source_board": "e-shopping",
            "search_keyword": "被騙",
            "imported_at": "2026-11-26",
            "human_notes": "不要公開",
            "reviewer": "bob",
            "stage1_flag": "第一階段已存在",
        }
    ]
    _write_items(review / "items.csv", stage1, fields)
    _write_items(
        review / "stage2_items.csv",
        stage2,
        fields + ["stage1_flag"],
    )
    status_fields = ["url", "status", "has_fuzzy_url_signal", "content", "reviewer"]
    with (data_dir / "ptt_article1_status.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=status_fields)
        writer.writeheader()
        writer.writerow(
            {
                "url": "https://www.ptt.cc/bbs/Bunco/M.1.html",
                "status": "exact_match",
                "has_fuzzy_url_signal": "false",
                "content": secret_sentence,
                "reviewer": "carol",
            }
        )
        writer.writerow(
            {
                "url": "https://www.ptt.cc/bbs/Bunco/M.2.html",
                "status": "temp",
                "has_fuzzy_url_signal": "true",
                "content": secret_sentence,
                "reviewer": "carol",
            }
        )
    answers = tmp_path / "answers.csv"
    with answers.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "review_id",
                "review_status",
                "content_relevant",
                "url_relevant",
                "keywords",
                "status",
                "human_notes",
                "reviewer",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "review_id": "ptt_test_1",
                "review_status": "reviewed",
                "content_relevant": "yes",
                "url_relevant": "no",
                "keywords": json.dumps(["假投資", "0911222333"], ensure_ascii=False),
                "status": "temp",
                "human_notes": "這是備註不能出去",
                "reviewer": "alice",
            }
        )
    ai_path = tmp_path / "ai.jsonl"
    ai_path.write_text(
        json.dumps(
            {
                "review_id": "ptt_test_1",
                "title": "標題 1",
                "content": secret_sentence,
                "evidence_quotes": ["這段全文只有內部檔才有"],
                "reasoning": "因為 " + secret_sentence,
                "reviewer": "alice",
                "human_notes": "note",
                "evidence_level": "suspected_case",
                "confidence": "high",
                "source_type": "ptt_article",
                "event_summary": "摘要不含電話 0911222333",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "dataset"
    manifest = export_all(
        root=root,
        out_dir=out_dir,
        answers_snapshot=answers,
        ai_jsonl=ai_path,
        write_browser_pii=False,
    )
    blob = "\n".join(path.read_text(encoding="utf-8-sig") for path in out_dir.iterdir())
    assert secret_sentence not in blob
    assert "alice" not in blob
    assert "bob" not in blob
    assert "這是備註不能出去" not in blob
    assert "0911222333" not in blob
    assert "0912-000-000" not in blob
    for path in out_dir.iterdir():
        if path.suffix not in {".jsonl", ".csv", ".json"} or path.name in {
            "dataset_manifest.json",
            "pii_patterns.json",
        }:
            continue
        text = path.read_text(encoding="utf-8-sig")
        for key in FORBIDDEN_KEYS:
            assert f'"{key}"' not in text or path.suffix == ".csv"
            if path.suffix == ".csv":
                header = text.splitlines()[0].lstrip("\ufeff")
                assert key not in header.split(",")

    relevance = [
        json.loads(line)
        for line in (out_dir / "anti_scam_ptt_relevance_v0.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(relevance) == 4
    assert manifest["counts"]["stage1_rows"] == 3
    assert manifest["counts"]["stage2_rows"] == 1
    overlapped = [row for row in relevance if row["dataset_type"] == "ptt_stage2_keyword"][0]
    assert overlapped["overlap_with_stage1"] is True
    matched = [row for row in relevance if row["review_id"] == "ptt_test_1"][0]
    assert matched["official_match_status"] == "exact_match"
    assert matched["review_status"] == "reviewed"
    assert matched["human_keywords"] == ["假投資", "[PHONE]"]
    unmatched = [row for row in relevance if row["review_id"] == "ptt_test_2"][0]
    assert unmatched["official_match_status"] == "no_exact_match"
    assert unmatched["official_fuzzy_url_signal"] is True
    titled = [row for row in relevance if row["review_id"] == "ptt_test_0"][0]
    assert titled["title_redacted"] is True
    assert "[PHONE]" in titled["title"]

    ai_public = json.loads(
        (out_dir / "anti_scam_ai_structured_v0.jsonl").read_text(encoding="utf-8").strip()
    )
    assert "evidence_quotes" not in ai_public
    assert "reasoning" not in ai_public
    assert secret_sentence not in json.dumps(ai_public, ensure_ascii=False)
    assert "[PHONE]" in ai_public["event_summary"]

    for name, info in manifest["files"].items():
        digest = hashlib.sha256((out_dir / name).read_bytes()).hexdigest()
        assert digest == info["sha256"]
    sums = (out_dir / "SHA256SUMS").read_text(encoding="utf-8")
    assert "anti_scam_ptt_relevance_v0.jsonl" in sums
    assert "CC0" in (out_dir / "LICENSE.md").read_text(encoding="utf-8")


def test_real_repo_export_counts_and_hashes(tmp_path):
    out_dir = tmp_path / "dataset"
    manifest = export_all(root=ROOT, out_dir=out_dir, write_browser_pii=False)
    assert manifest["counts"]["stage1_rows"] == 1190
    assert manifest["counts"]["stage2_rows"] == 116
    assert manifest["counts"]["overlap_urls"] == 8
    assert manifest["counts"]["relevance_rows"] == 1306
    assert manifest["license"] == "CC0-1.0"
    rows = [
        json.loads(line)
        for line in (out_dir / "anti_scam_ptt_relevance_v0.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert all(row["label_meaning"] == "topic_relevance_not_scam_truth" for row in rows)
    assert all(row["in_trusted_testset"] is False for row in rows)
    ids = [(row["dataset_type"], row["review_id"]) for row in rows]
    assert len(ids) == len(set(ids))
    # 從內部全文抽一句，確認沒有流進公開目錄。
    with (ROOT / "docs" / "review" / "items.csv").open(encoding="utf-8-sig", newline="") as handle:
        first = next(csv.DictReader(handle))
    title = first.get("title") or ""
    snippet = ""
    for line in (first.get("content") or "").splitlines():
        line = line.strip()
        if len(line) >= 24 and line not in title and title not in line:
            snippet = line[:48]
            break
    assert len(snippet) >= 24
    blob = "\n".join(
        path.read_text(encoding="utf-8-sig")
        for path in out_dir.iterdir()
        if path.suffix in {".jsonl", ".csv", ".json", ".md", ".txt"}
    )
    assert snippet not in blob
    for name, info in manifest["files"].items():
        digest = hashlib.sha256((out_dir / name).read_bytes()).hexdigest()
        assert digest == info["sha256"]
