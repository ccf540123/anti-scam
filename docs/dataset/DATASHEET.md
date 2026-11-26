# 反詐騙專題公開資料集資料卡（v0.1）

凍結日期：2026-11-26
授權：CC0 1.0 Universal（公有領域貢獻）
標籤意義常數：`topic_relevance_not_scam_truth`

## 這份資料是什麼

這是畢業專題的研究附錄，用來說明我們蒐集到哪些 PTT 文章、它們是否被標成「議題相關」，以及文章裡的網址有沒有出現在一份官方名單快照。

它不是法院認定的詐騙名單，也不是 Spam／Clean 資料集。引用這份資料，不等於引用「已確認詐騙案例」。

## 數字（各列不要加總成確認案例數）

| 清單 | 列數 | 說明 |
|---|---:|---|
| 第一階段 `ptt_candidate` | 1190 | 一列一篇審查清單文章 |
| 第二階段 `ptt_stage2_keyword` | 116 | 另一份清單，不是第一階段的子集 |
| 兩份清單網址重疊 | 8 | 重疊文章在兩個 dataset_type 各留一列 |
| 檔案總列數 | 1306 | 等於上面兩份列數相加，因為重疊列刻意各留一筆。這不是不重複文章數，也不是確認案例數 |
| 官方名單 exact_match | 0 | 只代表正文網址與官方快照 exact 相同。命中不等於詐騙成立，未命中不等於安全 |
| AI 結構化附錄 | 0 | 沒有原文，也沒有 evidence_quotes |
| 群眾自述 RAG 列 | 0 | 這次凍結是 0 列。核准後的群眾自述必須另標「群眾自述（未獨立查證）」，不能併進 PTT 列數 |

這次凍結沒有附上 Supabase 人審快照。因此 review_status 全部是 none，content_relevant 與 stage2_grade 先留空。線上儀表板仍會即時讀不含審查者姓名與備註的公開欄位；那不是這份凍結檔的官方筆數。

這次倉庫裡沒有 grok_batch_01_analysis_v2.jsonl，所以沒有附上 AI 結構化檔，也不補造 20 篇。

## 標籤怎麼讀

- `content_relevant`／`url_relevant`：人看過之後，覺得文章或其中網址「跟詐騙議題有沒有關」。yes／no 不是有罪或無罪。
- `stage2_grade`：A 值得保留、B 價值有限、C 無關。這不是 Spam／Clean。
- `evidence_level`：只有 AI 附錄才有。confirmed_case／suspected_case／related_article／cannot_determine。它不能從人審相關性直接推出來。
- `official_match_status`：`exact_match` 是官方 URL 快照 exact 命中；`no_exact_match` 對應內部狀態 `temp`（這份快照沒有 exact 命中）；`not_in_snapshot` 代表該網址不在 article1 狀態檔（狀態檔來自爬蟲 1,175 篇，不是 1,190 全覆蓋）。`official_fuzzy_url_signal` 只是短網址一類的模糊訊號，同樣不是定罪。狀態檔裡若有 exact 命中但不在這兩份審查清單，不會出現在上表，所以表上的 0 不是「整個 PTT 都沒有官方網址命中」。
- `label_meaning` 固定是 `topic_relevance_not_scam_truth`。

## 怎麼蒐集的

第一階段與第二階段清單來自 PTT（主要看板 Bunco、e-shopping、Bank_Service），搜尋詞以詐騙、被騙、匯款這類詞為主。關鍵字搜尋會讓資料偏向「標題或內文已經出現這些詞」的文章。年份大約從 2000 年代到 2026 年，手法新舊混在一起。這次已查的 Dcard 檔是空的，沒有放進公開包。

官方比對用的是專案裡的 `data/review/run_stage1_pipeline/ptt_article1_status.csv`。政府開放資料本身不在這個包裝裡重發。

## 故意沒放的欄位

- PTT 全文與推文（`content`）
- `human_notes`、`reviewer`
- `evidence_quotes`、未處理的 `reasoning`
- 任何 API 金鑰、審查口令、IP

標題、關鍵字與 AI 摘要會先跑電話、市話、身分證、Email、LINE ID、帳號樣式。掃到就遮蔽，並把 `title_redacted` 設為 true。規則擋不住所有中文姓名與間接識別，使用時仍要自己判斷。

## 測試集

主線可信測試集還沒有跟這份 v0.1 一起凍結。`in_trusted_testset` 全部是 false，`split` 全部是 unassigned。之後如果測試集定版，要重跑匯出，不能手改這兩個欄位。

## 授權與引用

本資料集以 CC0 1.0 貢獻到公有領域，任何人可以複製、修改、散布，包含商業使用，不必另外取得許可。詳見同目錄 `LICENSE.md` 與 https://creativecommons.org/publicdomain/zero/1.0/deed.zh-hant

CC0 只涵蓋我們有權釋出的欄位（識別碼、網址、標題、統計、標籤、去識別化摘要）。它不代表我們擁有 PTT 原文，原文本來就沒有放進這個包裝。

```
定偉（2026）。反詐騙專題 PTT 議題相關性資料集（版本 v0.1）[資料集]。
https://ccf540123.github.io/anti-scam/#dataset
```

```
Ding-Wei Chen (2026). Anti-scam PTT Topic-Relevance Dataset (v0.1) [Data set].
https://ccf540123.github.io/anti-scam/#dataset
```

## 維護

重新產生檔案：

```
python scripts/export_public_dataset.py
```

問題請回到專案儲存庫回報。下一版再用 v0.2，不要覆蓋已經發出的 v0.1 檔名而不改版本號。
