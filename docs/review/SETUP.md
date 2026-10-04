# Review 設定（兩分鐘）

你現在開的是 **Supabase 後台**；`docs/review/config.js` 在 **GitHub 專案**，兩邊不一樣。

## 1. 在 Supabase 拿兩個值

### Project URL
1. 看網址列，例如：  
   `https://supabase.com/dashboard/project/abcdefghijklmnop/settings/api-keys`
2. 中間那一段 `abcdefghijklmnop` 就是專案 ref
3. Project URL 填：`https://abcdefghijklmnop.supabase.co`

（也可到 Settings → **Data API** 或 **General** 複製 Project URL。）

### Publishable key
1. 留在 Settings → **API Keys**
2. 複製 **Publishable**（`sb_publishable_...`）
3. **不要**複製 Secret

## 2. 在 GitHub 改 config.js

直接打開這個連結編輯：

**https://github.com/ccf540123/anti-scam/edit/main/docs/review/config.js**

把三個欄位改成例如：

```js
window.REVIEW_CONFIG = {
  SUPABASE_URL: "https://你的專案ref.supabase.co",
  SUPABASE_ANON_KEY: "sb_publishable_貼上你複製的key",
  REVIEW_PASSWORD: "小組共同密碼",
  ITEMS_CSV_URL: "items.csv",
  DATASET_ID: "ptt_candidate",
};
```

然後按 **Commit changes**。

## 3. 在 Supabase 跑一次 SQL（若還沒跑）

1. Supabase → **SQL Editor** → New query
2. 貼上 repo 裡的 `scripts/supabase_ptt_review_answers.sql` 整段
3. Run

## 4. 打開 Review 頁

https://ccf540123.github.io/anti-scam/review/

用你設的 `REVIEW_PASSWORD` 登入。
