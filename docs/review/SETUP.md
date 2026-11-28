# 研究小組審查設定

公開網站在 `docs/index.html`。審查頁在 `docs/review/index.html`，只給研究小組。

登入畫面只問密碼。全組共用一個 Supabase Auth 帳號。帳號的 email 寫在 `docs/review/config.js` 的 `TEAM_LOGIN_EMAIL`（目前是 `review-team@example.com`）。這個 email 可以公開。密碼只放在 Supabase，不要寫進 GitHub、設定檔或前端程式。

沒有登入的人仍然讀不到、也改不了審查資料。資料庫用 `team_members` 和 RLS 把權限鎖在已登入、而且在名單裡的帳號。

## 1. 在 Supabase 執行遷移

1. 打開 SQL Editor
2. 貼上 `supabase/migrations/20261126120000_team_review_and_crowd.sql`
3. Run

這段 SQL 可以重複執行。它不會刪除既有的 `ptt_review_answers` 列。

## 2. 建立全組共用的一個帳號

這一步只要做一次。做完之後，組員打開審查頁，只輸入密碼就能進去。大家用同一組密碼，審查紀錄不會顯示是誰登入的。儲存時仍可在「檢視者」自己填名字。

1. 打開這個專案的 Supabase 後台。
2. 左邊點 **Authentication**，再點 **Users**。
3. 點 **Add user**，選建立新使用者。
4. Email 填 `review-team@example.com`。要和 `docs/review/config.js` 裡的 `TEAM_LOGIN_EMAIL` 完全一樣。
5. 設一組只有研究小組知道的密碼，再把這組密碼口頭或用安全的方式告訴組員。不要把密碼寫進 GitHub。
6. 勾選 **Auto Confirm User**（自動確認）。這樣不用收驗證信就能登入。
7. 按下建立。
8. 左邊點 **SQL Editor**，貼上下面這段，按 **Run**：

```sql
insert into public.team_members (user_id, email)
select id, email
from auth.users
where lower(email) = lower('review-team@example.com')
on conflict (user_id) do update set email = excluded.email;
```

這段只會把剛建立的共用帳號加進名單，不會刪除既有的審查答案。

9. 打開審查頁，只輸入第 5 步的密碼。密碼錯會停在登入畫面。密碼對，而且第 8 步有做，才會進審查。

如果後台不接受 `review-team@example.com`，改用另一個 email。然後把 `docs/review/config.js` 的 `TEAM_LOGIN_EMAIL` 改成同一個地址，SQL 裡的 email 也改成同一個地址。三處要一致。

密碼正確但還沒做第 8 步時，頁面會把人送回登入畫面，因為不在 `team_members` 裡就不能讀寫審查資料。舊的個人帳號可以留著，審查頁不會再請人輸入那些 email。

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
