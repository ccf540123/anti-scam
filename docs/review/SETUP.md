# 研究小組審查設定

公開網站在 `docs/index.html`。審查頁在 `docs/review/index.html`，只給研究小組。

登入用 Supabase Auth 的 email 與密碼。`docs/review/config.js` 只放 Project URL 和 Publishable key，不要放密碼或 service role key。

## 1. 在 Supabase 執行遷移

1. 打開 SQL Editor
2. 貼上 `supabase/migrations/20261126120000_team_review_and_crowd.sql`
3. Run

這段 SQL 可以重複執行。它不會刪除既有的 `ptt_review_answers` 列。

## 2. 建立組員帳號

1. Authentication → Users → Add user
2. 填組員 email 與密碼，並標成已確認（confirmed）
3. 回到 SQL Editor，把這個人寫進名單（把 email 換成真實地址）：

```sql
insert into public.team_members (user_id, email)
select id, email
from auth.users
where lower(email) = lower('member@example.com')
on conflict (user_id) do update set email = excluded.email;
```

不在 `team_members` 裡的帳號即使密碼正確，也進不了審查頁。

## 3. 部署投稿 Edge Function

在專案根目錄（已安裝 Supabase CLI，且已 `supabase login`）：

```bash
supabase link --project-ref telxfakoomkscqzhqgto
supabase functions deploy submit-scam-experience --no-verify-jwt
```

`--no-verify-jwt` 是因為這支函式開放給沒有登入的訪客。寫入仍用伺服器上的 service role，金鑰不會進到前端。

設定 Gemini 金鑰（沒有這把金鑰時，投稿仍會存檔，`ai_status` 為 `pending_key`）：

```bash
supabase secrets set GEMINI_API_KEY=你的金鑰
```

可選，用來給 IP 雜湊加鹽：

```bash
supabase secrets set SUBMISSION_HASH_SALT=一串隨機文字
```

不要把這兩個值寫進 GitHub。

## 4. 打開頁面

- 公開網站：https://ccf540123.github.io/anti-scam/
- 研究分析舊網址會轉到：https://ccf540123.github.io/anti-scam/#analysis
- 審查：https://ccf540123.github.io/anti-scam/review/
