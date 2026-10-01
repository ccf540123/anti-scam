# PTT 候選文章 Review dataset

此目錄由 `python run_import_ptt_review.py ...` 產生，與 Fuzzy review 分開。

- `items.csv`：匯入的候選文章（含 title / url / content / published_at / source_board / search_keyword）
- `answers.json`：人工標註結果（本機檔，預設不進版控）

匯入**不會**修改 `ptt_scam_cases.csv`，也不會動到 Fuzzy 的 CSV / answers。
