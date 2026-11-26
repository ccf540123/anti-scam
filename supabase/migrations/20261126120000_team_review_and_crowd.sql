-- 研究小組登入、審查權限收緊、群眾經驗投稿。
-- 可重複執行。不會刪除或改寫既有 ptt_review_answers 的列。
-- 授權只看 team_members 與 auth.uid()，不讀使用者自填的 metadata。

create table if not exists public.team_members (
  user_id uuid primary key references auth.users (id) on delete cascade,
  email text not null,
  created_at timestamptz not null default now()
);

create unique index if not exists team_members_email_idx
  on public.team_members (lower(email));

create table if not exists public.scam_submissions (
  submission_id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  status text not null default 'pending',
  ai_status text not null default 'pending_key',
  display_name text not null default '',
  anonymous_handle text not null,
  public_handle text not null,
  is_anonymous boolean not null default true,
  year_or_period text not null default '',
  region text not null default '',
  case_nature_self text not null default '',
  outcome_self text not null default '',
  amount_range text not null default '',
  channels jsonb not null default '[]'::jsonb,
  already_reported text not null default '',
  narrative_redacted text not null default '',
  narrative_hash text not null default '',
  possible_duplicate boolean not null default false,
  consent_research boolean not null default false,
  consent_ai boolean not null default false,
  source_type text not null default 'user_submission',
  ip_hash text not null default '',
  user_agent_hash text not null default '',
  review_notes text not null default '',
  reviewed_by text not null default '',
  reviewed_at timestamptz,
  rejection_reason text not null default ''
);

alter table public.scam_submissions
  add column if not exists ai_status text not null default 'pending_key';
alter table public.scam_submissions
  add column if not exists public_handle text;
alter table public.scam_submissions
  add column if not exists possible_duplicate boolean not null default false;

update public.scam_submissions
set public_handle = anonymous_handle
where public_handle is null or public_handle = '';

alter table public.scam_submissions
  alter column public_handle set not null;

alter table public.scam_submissions drop constraint if exists scam_submissions_status_check;
alter table public.scam_submissions
  add constraint scam_submissions_status_check
  check (status in ('pending', 'needs_redaction', 'approved', 'rejected'));

alter table public.scam_submissions drop constraint if exists scam_submissions_ai_status_check;
alter table public.scam_submissions
  add constraint scam_submissions_ai_status_check
  check (ai_status in ('pending_key', 'ready', 'qa_failed', 'error'));

alter table public.scam_submissions drop constraint if exists scam_submissions_source_type_check;
alter table public.scam_submissions
  add constraint scam_submissions_source_type_check
  check (source_type = 'user_submission');

alter table public.scam_submissions drop constraint if exists scam_submissions_consent_check;
alter table public.scam_submissions
  add constraint scam_submissions_consent_check
  check (consent_research = true and consent_ai = true);

alter table public.scam_submissions drop constraint if exists scam_submissions_narrative_len_check;
alter table public.scam_submissions
  add constraint scam_submissions_narrative_len_check
  check (char_length(narrative_redacted) <= 6000);

create unique index if not exists scam_submissions_handle_idx
  on public.scam_submissions (anonymous_handle);
create index if not exists scam_submissions_status_idx
  on public.scam_submissions (status, created_at desc);
create index if not exists scam_submissions_ip_hash_idx
  on public.scam_submissions (ip_hash, created_at desc);
create index if not exists scam_submissions_narrative_hash_idx
  on public.scam_submissions (narrative_hash);

create table if not exists public.scam_submission_ai (
  ai_id uuid primary key default gen_random_uuid(),
  submission_id uuid not null references public.scam_submissions (submission_id) on delete cascade,
  created_at timestamptz not null default now(),
  model_name text not null default '',
  prompt_version text not null default 'v2_rules_user_submission_1',
  source_type text not null default 'user_submission',
  article_relevance text not null default '',
  case_nature text not null default '',
  evidence_level text not null default '',
  incident_outcome text not null default '',
  outcome_subject text not null default '',
  outcome_notes text not null default '',
  scam_type jsonb not null default '[]'::jsonb,
  scam_tactics jsonb not null default '[]'::jsonb,
  victim_situation text not null default '',
  platforms jsonb not null default '[]'::jsonb,
  suspicious_signals jsonb not null default '[]'::jsonb,
  keywords jsonb not null default '[]'::jsonb,
  event_summary text not null default '',
  evidence_quotes jsonb not null default '[]'::jsonb,
  confidence text not null default '',
  reasoning text not null default '',
  qa_flags jsonb not null default '[]'::jsonb,
  token_input integer,
  token_output integer,
  status text not null default 'draft'
);

alter table public.scam_submission_ai drop constraint if exists scam_submission_ai_source_type_check;
alter table public.scam_submission_ai
  add constraint scam_submission_ai_source_type_check
  check (source_type = 'user_submission');

alter table public.scam_submission_ai drop constraint if exists scam_submission_ai_status_check;
alter table public.scam_submission_ai
  add constraint scam_submission_ai_status_check
  check (status in ('draft', 'qa_failed', 'ready_for_review', 'approved', 'rejected'));

create index if not exists scam_submission_ai_submission_idx
  on public.scam_submission_ai (submission_id, created_at desc);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
security invoker
set search_path = public
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists scam_submissions_set_updated_at on public.scam_submissions;
create trigger scam_submissions_set_updated_at
  before update on public.scam_submissions
  for each row
  execute function public.set_updated_at();

-- 組員判斷：只看自己在 team_members 的那一列，避免遞迴，也不用 security definer。
create or replace function public.is_team_member()
returns boolean
language sql
stable
security invoker
set search_path = public
as $$
  select exists (
    select 1
    from public.team_members
    where user_id = (select auth.uid())
  );
$$;

revoke all on function public.is_team_member() from public, anon, authenticated;
grant execute on function public.is_team_member() to authenticated;

revoke all on function public.set_updated_at() from public, anon, authenticated;
grant execute on function public.set_updated_at() to authenticated;

alter table public.team_members enable row level security;
alter table public.scam_submissions enable row level security;
alter table public.scam_submission_ai enable row level security;
alter table public.ptt_review_answers enable row level security;

revoke all on table public.team_members from anon, authenticated;
grant select on table public.team_members to authenticated;

drop policy if exists team_members_select_own on public.team_members;
create policy team_members_select_own
  on public.team_members
  for select
  to authenticated
  using (user_id = (select auth.uid()));

-- 舊的 anon 可寫、可讀審查者欄位政策全部拿掉。
drop policy if exists "ptt_review_answers_anon_select" on public.ptt_review_answers;
drop policy if exists "ptt_review_answers_anon_insert" on public.ptt_review_answers;
drop policy if exists "ptt_review_answers_anon_update_unlocked" on public.ptt_review_answers;
drop policy if exists "ptt_review_answers_anon_delete" on public.ptt_review_answers;
drop policy if exists ptt_review_answers_anon_select_safe on public.ptt_review_answers;
drop policy if exists ptt_review_answers_team_select on public.ptt_review_answers;
drop policy if exists ptt_review_answers_team_insert on public.ptt_review_answers;
drop policy if exists ptt_review_answers_team_update on public.ptt_review_answers;

revoke all on table public.ptt_review_answers from anon, authenticated;
grant select (
  review_id,
  dataset_id,
  content_relevant,
  url_relevant,
  keywords,
  status,
  review_status,
  article_type,
  saved_at,
  updated_at
) on table public.ptt_review_answers to anon;
grant select, insert, update on table public.ptt_review_answers to authenticated;

create policy ptt_review_answers_anon_select_safe
  on public.ptt_review_answers
  for select
  to anon
  using (true);

create policy ptt_review_answers_team_select
  on public.ptt_review_answers
  for select
  to authenticated
  using ((select public.is_team_member()));

create policy ptt_review_answers_team_insert
  on public.ptt_review_answers
  for insert
  to authenticated
  with check ((select public.is_team_member()));

create policy ptt_review_answers_team_update
  on public.ptt_review_answers
  for update
  to authenticated
  using ((select public.is_team_member()))
  with check ((select public.is_team_member()));

create or replace view public.ptt_review_answers_public
with (security_invoker = true) as
select
  review_id,
  dataset_id,
  content_relevant,
  url_relevant,
  keywords,
  status,
  review_status,
  article_type,
  saved_at,
  updated_at
from public.ptt_review_answers;

revoke all on table public.ptt_review_answers_public from anon, authenticated;
grant select on table public.ptt_review_answers_public to anon, authenticated;

revoke all on table public.scam_submissions from anon, authenticated;
grant select, update on table public.scam_submissions to authenticated;
grant select (
  submission_id,
  created_at,
  public_handle,
  year_or_period,
  region,
  case_nature_self,
  outcome_self,
  amount_range,
  channels,
  already_reported,
  source_type,
  status,
  consent_research,
  reviewed_at
) on table public.scam_submissions to anon;

drop policy if exists scam_submissions_team_select on public.scam_submissions;
create policy scam_submissions_team_select
  on public.scam_submissions
  for select
  to authenticated
  using ((select public.is_team_member()));

drop policy if exists scam_submissions_team_update on public.scam_submissions;
create policy scam_submissions_team_update
  on public.scam_submissions
  for update
  to authenticated
  using ((select public.is_team_member()))
  with check ((select public.is_team_member()));

drop policy if exists scam_submissions_anon_select_approved on public.scam_submissions;
create policy scam_submissions_anon_select_approved
  on public.scam_submissions
  for select
  to anon
  using (status = 'approved' and consent_research = true);

revoke all on table public.scam_submission_ai from anon, authenticated;
grant select, update on table public.scam_submission_ai to authenticated;
grant select (
  ai_id,
  submission_id,
  created_at,
  source_type,
  article_relevance,
  case_nature,
  evidence_level,
  incident_outcome,
  scam_type,
  platforms,
  event_summary,
  confidence,
  status
) on table public.scam_submission_ai to anon;

drop policy if exists scam_submission_ai_team_select on public.scam_submission_ai;
create policy scam_submission_ai_team_select
  on public.scam_submission_ai
  for select
  to authenticated
  using ((select public.is_team_member()));

drop policy if exists scam_submission_ai_team_update on public.scam_submission_ai;
create policy scam_submission_ai_team_update
  on public.scam_submission_ai
  for update
  to authenticated
  using ((select public.is_team_member()))
  with check ((select public.is_team_member()));

drop policy if exists scam_submission_ai_anon_select_approved on public.scam_submission_ai;
create policy scam_submission_ai_anon_select_approved
  on public.scam_submission_ai
  for select
  to anon
  using (
    exists (
      select 1
      from public.scam_submissions as submission
      where submission.submission_id = scam_submission_ai.submission_id
        and submission.status = 'approved'
        and submission.consent_research = true
    )
  );

-- 公開摘要：不含正文、IP、審查備註、引句與推理。security_invoker 讓上面的 RLS 繼續生效。
create or replace view public.scam_submissions_public
with (security_invoker = true) as
select
  submission.submission_id,
  submission.created_at,
  submission.public_handle,
  submission.year_or_period,
  submission.region,
  submission.case_nature_self,
  submission.outcome_self,
  submission.amount_range,
  submission.channels,
  submission.already_reported,
  submission.source_type,
  ai.evidence_level,
  ai.incident_outcome,
  ai.scam_type,
  ai.platforms,
  ai.event_summary,
  ai.confidence
from public.scam_submissions as submission
left join lateral (
  select
    latest.evidence_level,
    latest.incident_outcome,
    latest.scam_type,
    latest.platforms,
    latest.event_summary,
    latest.confidence
  from public.scam_submission_ai as latest
  where latest.submission_id = submission.submission_id
  order by latest.created_at desc
  limit 1
) as ai on true
where submission.status = 'approved'
  and submission.consent_research = true;

revoke all on table public.scam_submissions_public from anon, authenticated;
grant select on table public.scam_submissions_public to anon, authenticated;

-- 排行榜需要 distinct narrative_hash，但 anon 不該直接讀雜湊或暱稱原欄。
-- 這個函式只回傳已核准的代號與件數，search_path 鎖住，不讀其他 schema。
create or replace function public.crowd_leaderboard()
returns table (
  public_handle text,
  approved_count integer,
  last_approved_at timestamptz
)
language sql
stable
security definer
set search_path = public
as $$
  select
    submission.public_handle,
    count(distinct submission.narrative_hash)::integer as approved_count,
    max(submission.reviewed_at) as last_approved_at
  from public.scam_submissions as submission
  where submission.status = 'approved'
    and submission.consent_research = true
    and submission.narrative_hash <> ''
  group by submission.public_handle
  order by approved_count desc, last_approved_at desc nulls last;
$$;

create or replace function public.crowd_public_stats()
returns jsonb
language sql
stable
security definer
set search_path = public
as $$
  select jsonb_build_object(
    'approved_count',
    (
      select count(*)::integer
      from public.scam_submissions
      where status = 'approved' and consent_research = true
    ),
    'label', '群眾自述（未獨立查證）',
    'note', '與 PTT 人審清單不可加總。官方名單命中也不等於詐騙成立。'
  );
$$;

revoke all on function public.crowd_leaderboard() from public, anon, authenticated;
revoke all on function public.crowd_public_stats() from public, anon, authenticated;
grant execute on function public.crowd_leaderboard() to anon, authenticated;
grant execute on function public.crowd_public_stats() to anon, authenticated;

-- public 裡每一張表都打開 RLS。沒有政策的表，anon 與 authenticated 讀不到。
do $$
declare
  table_name text;
begin
  for table_name in
    select cls.relname
    from pg_class as cls
    join pg_namespace as nsp on nsp.oid = cls.relnamespace
    where nsp.nspname = 'public'
      and cls.relkind = 'r'
  loop
    execute format('alter table public.%I enable row level security', table_name);
  end loop;
end;
$$;
