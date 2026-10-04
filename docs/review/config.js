/*
  GitHub Pages Review 設定（可公開；不要放 Secret / service_role key）

  ★ 這個檔案在 GitHub 專案裡，不在 Supabase 後台。
  ★ 用瀏覽器直接改：
    https://github.com/ccf540123/anti-scam/edit/main/docs/review/config.js
  ★ 改完按 Commit changes → 推到 main 後，Pages 會自動更新。

  三個值怎麼填：

  1) SUPABASE_URL（Project URL）
     - 看瀏覽器網址列：
       https://supabase.com/dashboard/project/【這一段】/settings/...
     - 填成：https://【這一段】.supabase.co
     - 或到左側 Settings → Data API / General，複製 Project URL

  2) SUPABASE_ANON_KEY
     - Supabase → Settings → API Keys
     - 複製 Publishable key（sb_publishable_...）
     - 不要用 Secret key

  3) REVIEW_PASSWORD
     - 研究小組共同進入密碼（前端可見，只是簡易門檻）
*/
window.REVIEW_CONFIG = {
  SUPABASE_URL: "https://YOUR_PROJECT.supabase.co",
  SUPABASE_ANON_KEY: "YOUR_SUPABASE_ANON_PUBLIC_KEY",
  REVIEW_PASSWORD: "change_me_research_group_password",
  ITEMS_CSV_URL: "items.csv",
  DATASET_ID: "ptt_candidate",
};
