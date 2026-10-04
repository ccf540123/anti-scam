/*
  GitHub Pages Review 設定（可公開；不要放 service_role key）

  填好後 commit + push 到 main，Pages 就會更新。

  SUPABASE_URL / SUPABASE_ANON_KEY：
    Supabase → Project Settings → API
    使用 anon public key（不是 service_role）

  REVIEW_PASSWORD：
    研究小組共同進入密碼（前端可見，只是簡易門檻；真正資料保護靠 RLS）
*/
window.REVIEW_CONFIG = {
  SUPABASE_URL: "https://YOUR_PROJECT.supabase.co",
  SUPABASE_ANON_KEY: "YOUR_SUPABASE_ANON_PUBLIC_KEY",
  REVIEW_PASSWORD: "change_me_research_group_password",
  ITEMS_CSV_URL: "items.csv",
  DATASET_ID: "ptt_candidate",
};
