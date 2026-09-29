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

1. 到 [Render](https://render.com/) 註冊並連線你的 GitHub
2. New → Web Service → 選擇這個 repo
3. 設定：
   - **Runtime**：Python
   - **Build Command**：`pip install -r requirements.txt`
   - **Start Command**：`gunicorn app:app --bind 0.0.0.0:$PORT --timeout 120`
4. Environment 新增：
   - `GEMINI_API_KEY_1`
   - `GEMINI_API_KEY_2`（可選）
   - `GEMINI_API_KEY_3`（可選）
   - `FRONTEND_ORIGIN` = 你的 GitHub Pages 網址  
     例如 `https://ccf540123.github.io`  
     或 `https://ccf540123.github.io/anti-scam-LINE-bot`
5. 部署完成後，記下後端網址，例如：
   `https://anti-scam-api.onrender.com`
6. 可用瀏覽器打開：
   `https://anti-scam-api.onrender.com/api/health`  
   看到 `{"status":"ok"}` 代表成功

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

## API

- `GET /api/health`：健康檢查
- `POST /api/check`：JSON `{ "text": "..." }` → `{ "result": "..." }`
- `POST /api/check-image`：FormData 欄位 `image` → `{ "result": "..." }`

## 安全提醒

- Gemini API Key **只**放在本機 `.env` 或 Render Environment
- **不要**把 `.env`、金鑰寫進 `docs/` 或任何前端檔案
- `.gitignore` 已忽略 `.env`、`env/`、`__pycache__/`
