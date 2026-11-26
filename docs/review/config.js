/*
  GitHub Pages Review 設定（可公開；不要放 Secret / service_role key，也不要放密碼）

  1) SUPABASE_URL：Settings → Data API 的 Project URL
  2) SUPABASE_ANON_KEY：Settings → API Keys 的 Publishable key（sb_publishable_...）
     不要用 Secret key。

  登入改走 Supabase Auth。組員要先在 Authentication 建立帳號，
  再由管理員把 email 寫進 public.team_members。
*/
window.REVIEW_CONFIG = {
  SUPABASE_URL: "https://telxfakoomkscqzhqgto.supabase.co",
  SUPABASE_ANON_KEY: "sb_publishable_mp3XIM9dNud_vAceBmJzuQ_FN7_pTBr",
  ITEMS_CSV_URL: "items.csv",
  DATASET_ID: "ptt_candidate",
  STAGE2_ITEMS_CSV_URL: "stage2_items.csv",
  STAGE2_DATASET_ID: "ptt_stage2_keyword",
};
