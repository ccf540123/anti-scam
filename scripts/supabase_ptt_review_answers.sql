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

-- 前端只用 anon key；允許讀取全部答案
drop policy if exists "ptt_review_answers_anon_select" on public.ptt_review_answers;
create policy "ptt_review_answers_anon_select"
  on public.ptt_review_answers
  for select
  to anon
  using (true);

-- 允許新增（未審文章第一次儲存）
drop policy if exists "ptt_review_answers_anon_insert" on public.ptt_review_answers;
create policy "ptt_review_answers_anon_insert"
  on public.ptt_review_answers
  for insert
  to anon
  with check (true);

-- 僅允許更新「尚未 reviewed」的列（已完成鎖定）
drop policy if exists "ptt_review_answers_anon_update_unlocked" on public.ptt_review_answers;
create policy "ptt_review_answers_anon_update_unlocked"
  on public.ptt_review_answers
  for update
  to anon
  using (coalesce(review_status, '') <> 'reviewed')
  with check (true);

-- 禁止 anon 刪除
drop policy if exists "ptt_review_answers_anon_delete" on public.ptt_review_answers;
create policy "ptt_review_answers_anon_delete"
  on public.ptt_review_answers
  for delete
  to anon
  using (false);
