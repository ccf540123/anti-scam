-- PTT Temp Review answers（GitHub Pages 前端 + Supabase）
-- 在 Supabase Dashboard → SQL Editor 執行整段。
-- 若 table 已存在，也可只跑下方 RLS 區塊。

create table if not exists public.ptt_review_answers (
  review_id text primary key,
  dataset_id text not null default 'ptt_candidate',
  content_relevant text not null default '',
  url_relevant text not null default '',
  keywords jsonb not null default '[]'::jsonb,
  status text not null default 'temp',
  human_notes text not null default '',
  reviewer text not null default '',
  review_status text not null default 'pending',
  article_type text not null default '',
  saved_at timestamptz,
  updated_at timestamptz not null default now()
);

create index if not exists ptt_review_answers_dataset_idx
  on public.ptt_review_answers (dataset_id);

create index if not exists ptt_review_answers_review_status_idx
  on public.ptt_review_answers (review_status);

alter table public.ptt_review_answers enable row level security;

-- 2026-11-26 起，anon 不再能寫入，也不能讀 reviewer / human_notes。
-- 正式政策在 supabase/migrations/20261126120000_team_review_and_crowd.sql。
-- 這份舊檔只負責刪掉先前過寬的政策，避免有人重跑後又把表打開。
drop policy if exists "ptt_review_answers_anon_select" on public.ptt_review_answers;
drop policy if exists "ptt_review_answers_anon_insert" on public.ptt_review_answers;
drop policy if exists "ptt_review_answers_anon_update_unlocked" on public.ptt_review_answers;
drop policy if exists "ptt_review_answers_anon_delete" on public.ptt_review_answers;
