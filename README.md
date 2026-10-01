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
`docs/config.js` 的 `API_BASE_URL` 請保持空字串 `""`。

## 正式部署

### A. 部署 Flask Backend 到 Render

專案已附 `render.yaml`，可用兩種方式：

#### 方法一：Blueprint（建議）

1. 到 [Render Dashboard](https://dashboard.render.com/)
2. **New → Blueprint**
3. 連線 GitHub，選 repo：`anti-scam-LINE-bot`，branch：`main`
4. Render 會讀取 `render.yaml`
5. 填入環境變數（金鑰只在這裡填，不要放到 GitHub）：
   - `GEMINI_API_KEY_1`
   - `GEMINI_API_KEY_2`（可選）
   - `GEMINI_API_KEY_3`（可選）
6. Apply / Create
7. 部署完成後，記下後端網址，例如：
   `https://anti-scam-api.onrender.com`

#### 方法二：手動 Web Service

1. **New → Web Service**
2. 選 repo：`anti-scam-LINE-bot`，branch：`main`
3. 填這些欄位：
   - **Name**：`anti-scam-api`
   - **Language / Runtime**：`Python 3`
   - **Build Command**：`pip install -r requirements.txt`
   - **Start Command**：`gunicorn app:app --bind 0.0.0.0:$PORT --timeout 120`
   - **Instance type**：Free
4. **Environment** 新增：
   - `GEMINI_API_KEY_1` = 你的金鑰
   - `GEMINI_API_KEY_2` =（可選）
   - `GEMINI_API_KEY_3` =（可選）
   - `FRONTEND_ORIGIN` = `https://ccf540123.github.io`
5. Create Web Service

部署後測試：

```text
https://你的服務名.onrender.com/api/health
```

看到 `{"status":"ok"}` 代表成功。

> Render 免費方案一段時間沒人用可能會睡著，第一次開啟可能要等十幾秒。

### B. 部署 Frontend 到 GitHub Pages

1. 編輯 `docs/config.js`，把 API 網址改成 Render 網址：

```js
window.API_BASE_URL = "https://anti-scam-api.onrender.com";
```

2. 把變更 commit / push 到 GitHub
3. GitHub repo → **Settings → Pages**
4. Source 選 **Deploy from a branch**
5. Branch 選 `main`（或你的正式分支），Folder 選 **/docs**
6. 儲存後等待一兩分鐘

老師與同學要開的網址通常是：

```text
https://你的GitHub帳號.github.io/anti-scam-LINE-bot/
```

## 啟動方式對照

| 情境 | 怎麼啟動 | 誰負責開著 |
|------|----------|------------|
| 本機測試 | `python app.py` | 你的電腦要開著 |
| 正式後端 | Render 自動用 `gunicorn app:app ...` | Render 雲端，不必開筆電 |
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
3. 通過後才會載入審查資料並可儲存標註
4. 可隨時匯出 CSV（欄位與原本 fuzzy review 相同）

沒有登入時，`/api/review/items`、`/api/review/save`、`/api/review/export.csv` 都會回 401。

## 更新 PTT 案例 CSV（給 RAG 用）

爬蟲輸出 `ptt_scam_cases.csv`。`rag_searcher.py` 會讀取其中的 `title`、`url`、`content`、`source`（多出來的 metadata 欄位可忽略）。

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
