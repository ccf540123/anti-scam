-- PTT Temp Review answers（多人共用永久儲存）
-- 在 Supabase Dashboard → SQL Editor 執行整段即可。

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

-- 後端用 service role key 存取；關閉匿名讀寫
alter table public.ptt_review_answers enable row level security;

-- 不建立 anon/authenticated policy：僅 service_role 可透過 API key 存取
