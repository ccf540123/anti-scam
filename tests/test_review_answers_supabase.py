"""Supabase Review answers backend (mocked HTTP)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ["REVIEW_PASSWORD"] = "test-review-pass"
os.environ["FLASK_SECRET_KEY"] = "test-secret-key-for-unit-tests"
# Ensure tests default to local file unless explicitly testing supabase
os.environ.pop("SUPABASE_URL", None)
os.environ.pop("SUPABASE_SERVICE_ROLE_KEY", None)
os.environ.pop("SUPABASE_KEY", None)

from modules import review_answers_store, review_store  # noqa: E402


class TestSupabaseAnswersStore(unittest.TestCase):
    def test_fetch_all_and_upsert_via_rest(self):
        with patch.dict(
            os.environ,
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_SERVICE_ROLE_KEY": "service-role-test",
            },
        ):
            self.assertTrue(review_answers_store.supabase_configured())

            get_resp = MagicMock()
            get_resp.status_code = 200
            get_resp.json.return_value = [
                {
                    "review_id": "ptt_abc",
                    "dataset_id": "ptt_candidate",
                    "content_relevant": "yes",
                    "url_relevant": "no",
                    "keywords": ["假投資"],
                    "status": "temp",
                    "human_notes": "",
                    "reviewer": "alice",
                    "review_status": "reviewed",
                    "article_type": "",
                    "saved_at": "2026-10-02T00:00:00Z",
                }
            ]

            post_resp = MagicMock()
            post_resp.status_code = 201
            post_resp.json.return_value = [
                {
                    "review_id": "ptt_new",
                    "dataset_id": "ptt_candidate",
                    "content_relevant": "no",
                    "url_relevant": "none",
                    "keywords": [],
                    "status": "non_match",
                    "human_notes": "",
                    "reviewer": "bob",
                    "review_status": "reviewed",
                    "article_type": "",
                    "saved_at": "2026-10-02T01:00:00Z",
                }
            ]

            with patch(
                "modules.review_answers_store.requests.get",
                return_value=get_resp,
            ) as mock_get, patch(
                "modules.review_answers_store.requests.post",
                return_value=post_resp,
            ) as mock_post:
                all_answers = review_answers_store.fetch_all_answers("ptt_candidate")
                self.assertEqual(all_answers["ptt_abc"]["reviewer"], "alice")
                self.assertEqual(all_answers["ptt_abc"]["keywords"], ["假投資"])

                saved = review_answers_store.upsert_one_answer(
                    "ptt_new",
                    {
                        "content_relevant": "no",
                        "url_relevant": "none",
                        "keywords": [],
                        "status": "non_match",
                        "reviewer": "bob",
                        "review_status": "reviewed",
                        "saved_at": "2026-10-02T01:00:00Z",
                    },
                    "ptt_candidate",
                )
                self.assertEqual(saved["status"], "non_match")
                mock_get.assert_called()
                mock_post.assert_called()
                args, kwargs = mock_post.call_args
                self.assertIn("ptt_review_answers", args[0])
                self.assertEqual(kwargs["json"]["review_id"], "ptt_new")

    def test_review_store_uses_supabase_when_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            items = Path(tmp) / "items.csv"
            items.write_text(
                "review_id,dataset_type,dedup_key,title,article_url,content,"
                "published_at,source,source_board,search_keyword,imported_at,"
                "review_status,status,article_type,human_notes,reviewer\n"
                "ptt_x,ptt_candidate,https://www.ptt.cc/bbs/Bunco/M.x.html,"
                "[心得] x,https://www.ptt.cc/bbs/Bunco/M.x.html,body,Mon,ptt,"
                "Bunco,詐騙,2026-01-01T00:00:00Z,pending,temp,,,\n",
                encoding="utf-8-sig",
            )
            with patch.dict(
                os.environ,
                {
                    "SUPABASE_URL": "https://example.supabase.co",
                    "SUPABASE_SERVICE_ROLE_KEY": "service-role-test",
                    "REVIEW_PTT_ITEMS_CSV": str(items),
                },
            ), patch(
                "modules.review_answers_store.fetch_all_answers",
                return_value={},
            ), patch(
                "modules.review_answers_store.fetch_one_answer",
                return_value=None,
            ), patch(
                "modules.review_answers_store.upsert_one_answer",
                return_value={
                    "content_relevant": "yes",
                    "url_relevant": "no",
                    "keywords": ["詞"],
                    "status": "temp",
                    "human_notes": "",
                    "reviewer": "cara",
                    "review_status": "reviewed",
                    "article_type": "",
                    "saved_at": "2026-10-02T02:00:00Z",
                },
            ) as mock_upsert:
                self.assertEqual(review_store.answers_storage_backend(), "supabase")
                saved = review_store.upsert_answer(
                    "ptt_x",
                    {
                        "content_relevant": "yes",
                        "url_relevant": "no",
                        "keywords": ["詞"],
                        "reviewer": "cara",
                    },
                    "ptt_candidate",
                )
                self.assertEqual(saved["reviewer"], "cara")
                mock_upsert.assert_called_once()


if __name__ == "__main__":
    unittest.main()
