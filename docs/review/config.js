/*
  GitHub Pages Review 設定（可公開；不要放 Secret / service_role key，也不要放密碼）

  1) SUPABASE_URL：Settings → Data API 的 Project URL
  2) SUPABASE_ANON_KEY：Settings → API Keys 的 Publishable key（sb_publishable_...）
     不要用 Secret key。

  登入畫面只問密碼。全組共用下面這個 Supabase Auth 帳號。
  TEAM_LOGIN_EMAIL 不是密碼，可以公開。
  密碼只放在 Supabase Authentication，不要寫進這個檔案。
  管理員要建立這個帳號，並把它寫進 public.team_members。
  步驟見 SETUP.md。
*/
window.REVIEW_CONFIG = {
  SUPABASE_URL: "https://telxfakoomkscqzhqgto.supabase.co",
  SUPABASE_ANON_KEY: "sb_publishable_mp3XIM9dNud_vAceBmJzuQ_FN7_pTBr",
  TEAM_LOGIN_EMAIL: "review-team@example.com",
  ITEMS_CSV_URL: "items.csv",
  DATASET_ID: "ptt_candidate",
  STAGE2_ITEMS_CSV_URL: "stage2_items.csv",
  STAGE2_DATASET_ID: "ptt_stage2_keyword",
};
