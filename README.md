# 反詐騙檢測 Website

校內專題用的反詐騙檢測網站。

- **Frontend**：GitHub Pages（`docs/`）
- **Backend**：Flask API（部署到 Render）
- **AI**：Google Gemini（金鑰只放後端環境變數）

不再需要 LINE Webhook、LINE token、ngrok。

## 架構

```text
瀏覽器（GitHub Pages）
   │  fetch
   ▼
Flask API（Render）
   │
   ├─ modules/url_checker.py
   ├─ modules/text_checker.py
   ├─ modules/image_checker.py
   └─ modules/rag_searcher.py + CSV
```

## 本機開發

### 1. 建立虛擬環境並安裝套件

需要 Python 3.12+。

```bash
python3.12 -m venv env
source env/bin/activate
pip install -r requirements.txt
```

### 2. 設定本機環境變數

```bash
cp .env.example .env
```

編輯 `.env`，填入：

```env
GEMINI_API_KEY_1=你的金鑰
GEMINI_API_KEY_2=你的第二組金鑰
GEMINI_API_KEY_3=你的第三組金鑰
FRONTEND_ORIGIN=*
```

### 3. 啟動後端（本機）

```bash
python app.py
```

開啟：

```text
http://127.0.0.1:5001
```

本機時，Flask 會順便提供 `docs/` 前端頁面，方便測試。  
正式的 `docs/config.js` 指向 `https://anti-scam-line-bot.onrender.com`。若要讓本機頁面打自己電腦上的後端，測試時把 `API_BASE_URL` 暫時改回空字串 `""`。

`python app.py` 只啟動網站。它不會爬 PTT 或 Dcard，也不會覆寫 `ptt_scam_cases.csv`、`dcard_scam_cases.csv`、`scam_165_urls.csv`。165 名單會試著下載到記憶體；下載失敗就讀 repo 裡的本地快照。

要手動更新語料時，另外執行：

```bash
python run_ptt_crawl.py
python run_dcard_crawl.py
```

## 正式部署

### A. 部署 Flask Backend 到 Render

專案已附 `render.yaml`，可用兩種方式：

#### 方法一：Blueprint（建議）

1. 到 [Render Dashboard](https://dashboard.render.com/)
2. **New → Blueprint**
3. 連線 GitHub，選 repo：`ccf540123/anti-scam`，branch：`main`
4. 執行個體請選 **Free**（$0）。不要選付費方案。
5. Render 會讀取 `render.yaml`
6. 在 Dashboard 填環境變數（不要寫進 GitHub）：
   - `GEMINI_API_KEY_1`（必填才會呼叫 Gemini；沒有這把金鑰時，網站仍可啟動，AI 分析會走離線文案）
7. Apply / Create
8. 現在這台服務的網址是 `https://anti-scam-line-bot.onrender.com`。`/api/health` 回 `{"status":"ok"}` 才算可用。不要改用 `anti-scam-api.onrender.com`。

#### 方法二：手動 Web Service

1. **New → Web Service**
2. 選 repo：`ccf540123/anti-scam`，branch：`main`
3. 填這些欄位：
   - **Name**：`anti-scam-api`（若這個名字已被別的服務占用，換一個新名字）
   - **Language / Runtime**：`Python 3`
   - **Build Command**：`pip install -r requirements.txt`
   - **Start Command**：`gunicorn app:app --bind 0.0.0.0:$PORT --timeout 120`
   - **Instance type**：Free（$0）。不要選付費方案。
   - **Health Check Path**：`/api/health`
4. **Environment** 新增：
   - `GEMINI_API_KEY_1` = 你的金鑰（只放在這裡）
   - `FRONTEND_ORIGIN` = `https://ccf540123.github.io`
5. Create Web Service

部署後測試：

```text
https://你的服務名.onrender.com/api/health
```

看到 `{"status":"ok"}` 代表成功。

> Render 免費方案約 15 分鐘沒人用會睡著，下次打開可能要等約 1 分鐘。每個 workspace 一個月有 750 個免費 instance hours。睡著或重新部署時，機器上的暫存檔會消失，所以啟動程序不會把 165 或 PTT 名單寫回磁碟，而是使用 repo 裡的 CSV 快照。

### B. 部署 Frontend 到 GitHub Pages

`docs/config.js` 這一行已經指向現有的 Render 服務：

```js
window.API_BASE_URL = "https://anti-scam-line-bot.onrender.com";
```

這一行推上 `main` 之後，GitHub Pages 的分析按鈕才會改打這台後端。

Pages 若還沒打開：

1. GitHub repo → **Settings → Pages**
2. Source 選 **Deploy from a branch**
3. Branch 選 `main`，Folder 選 **/docs**
4. 儲存後等一兩分鐘

老師與同學要開的網址是：

```text
https://ccf540123.github.io/anti-scam/
```

## 啟動方式對照

| 情境 | 怎麼啟動 | 誰負責開著 |
|------|----------|------------|
| 本機測試 | `python app.py`（不爬蟲、不覆寫 CSV） | 你的電腦要開著 |
| 手動更新 PTT／Dcard | `python run_ptt_crawl.py`、`python run_dcard_crawl.py` | 只有你明確執行時才會抓資料 |
| 正式後端 | Render Free，`gunicorn app:app ...` | Render 雲端，不必開筆電 |
| 正式前端 | GitHub Pages 托管 `docs/` | GitHub，不必開筆電 |

## 研究小組 Review（密碼保護）

公開檢測網站仍是 GitHub Pages 的 `docs/`。  
人工審查介面只掛在 **Flask 後端**，路徑：

```text
http://127.0.0.1:5001/review
```

正式環境則是：

```text
https://你的-render網址/review
```

請在 `.env` 或 Render Environment 設定：

```env
REVIEW_PASSWORD=你們小組共同密碼
FLASK_SECRET_KEY=一長串隨機字串
```

使用流程：

1. 打開 `/review`
2. 輸入共同密碼
3. 在右上角資料集切換：**Fuzzy 候選文章** 或 **PTT 候選文章**
4. 通過後才會載入審查資料並可儲存標註
5. 可隨時匯出目前資料集的 CSV

沒有登入時，`/api/review/items`、`/api/review/save`、`/api/review/export.csv` 都會回 401。

### 匯入 PTT 候選到 Review（獨立資料，不覆蓋 Fuzzy）

爬蟲產出的 `ptt_scam_cases.csv` **不會**自動進 Review，也**不會**被匯入腳本修改。  
請明確指定要匯入的範圍，寫入獨立目錄 `data/review/ptt_candidates/`：

```bash
# 先匯入少量試看
python run_import_ptt_review.py --limit 20

# 依看板／關鍵字篩選
python run_import_ptt_review.py --boards Bunco --keywords 被騙 --limit 50

# 指定 URL 清單（一行一個）
python run_import_ptt_review.py --urls-file urls.txt

# 明確匯入來源檔全部列
python run_import_ptt_review.py --all
```

- Fuzzy 標註仍存在原本的 answers 檔，不會被 PTT 匯入蓋掉
- PTT 標註存到 `data/review/ptt_candidates/answers.json`，用穩定 `review_id`（由文章 URL 產生）對應
- 公開檢測與 RAG 仍只讀 `ptt_scam_cases.csv`，不受 Review 影響

## 更新 PTT 案例 CSV（給 RAG 用）

爬蟲輸出 `ptt_scam_cases.csv`。`rag_searcher.py` 會讀取其中的 `title`、`url`、`content`、`source`（多出來的 metadata 欄位可忽略）。

第一階段 Article 1 在爬蟲後預設 `status=temp`。執行 URL cross-reference 後會產生文章層級狀態檔（`ptt_article1_status.csv`）：

- `exact_match`：正文 URL 與官方資料 exact 命中
- `temp`：尚無 exact（等待人工；**不是** non_match）

Fuzzy（短網址等）仍輸出到既有 Fuzzy Review CSV，與 `temp` / `non_match` 分開。`non_match` 留給之後人工檢查，不會由自動 cross-reference 產生。

看板與關鍵字集中寫在 `crawlers/ptt_crawler.py` 的 `BOARDS`、`KEYWORDS`。  
日常直接執行即可（不必每次手打參數）：

```bash
python run_ptt_crawl.py
python run_ptt_crawl.py --pages 10
python run_ptt_crawl.py --dry-run
```

若要臨時覆寫範圍，仍可用 CLI：

```bash
python run_ptt_crawl.py \
  --boards Bunco \
  --keywords 詐騙 \
  --pages 5 \
  --output ptt_scam_cases.csv
```

完成後會寫入 CSV，並額外產生 `ptt_scam_cases_summary.json`（不取代 CSV）。

單元測試（不連 PTT）：

```bash
python -m unittest tests.test_ptt_crawler_multi -v
```

## API

- `GET /api/health`：健康檢查
- `POST /api/check`：JSON `{ "text": "..." }` → `{ "result": "..." }`
- `POST /api/check-image`：FormData 欄位 `image` → `{ "result": "..." }`

## 安全提醒

- Gemini API Key **只**放在本機 `.env` 或 Render Environment
- **不要**把 `.env`、金鑰寫進 `docs/` 或任何前端檔案
- `.gitignore` 已忽略 `.env`、`env/`、`__pycache__/`
