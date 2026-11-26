"""靜態檢查遷移 SQL，避免把審查表重新開放給 anon。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT / "supabase" / "migrations" / "20261126120000_team_review_and_crowd.sql"
).read_text(encoding="utf-8")
OLD_SQL = (ROOT / "scripts" / "supabase_ptt_review_answers.sql").read_text(encoding="utf-8")


def test_migration_locks_down_review_and_enables_rls():
    text = MIGRATION.lower()
    assert "enable row level security" in text
    assert "auth.role()" not in text
    assert "user_metadata" not in text
    assert "create table if not exists public.team_members" in text
    assert "create table if not exists public.scam_submissions" in text
    assert "create table if not exists public.scam_submission_ai" in text
    assert "security_invoker = true" in text
    assert "ptt_review_answers_team_update" in text
    assert "with check ((select public.is_team_member()))" in text
    assert "human_notes" not in MIGRATION.split("create or replace view public.ptt_review_answers_public")[1].split("revoke all")[0]
    assert "evidence_quotes" not in MIGRATION.split("create or replace view public.scam_submissions_public")[1].split("revoke all")[0]
    assert "narrative_redacted" not in MIGRATION.split("create or replace view public.scam_submissions_public")[1].split("revoke all")[0]


def test_old_review_sql_does_not_reopen_anon_writes():
    assert 'create policy "ptt_review_answers_anon_insert"' not in OLD_SQL
    assert "with check (true)" not in OLD_SQL
    assert "to anon" not in OLD_SQL.lower() or "drop policy" in OLD_SQL
