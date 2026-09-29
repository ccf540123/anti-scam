# 🛡️ anti-scam-LINE-bot（防詐騙檢測）

這是一個基於 Python Flask 的反詐騙專案。  
原本是 LINE Bot，現在也支援直接在瀏覽器使用的 Website。

## ✨ 主要功能
* 🔍 **詐騙訊息分析**：貼上可疑訊息或網址，由系統評估風險
* 🚨 **165 黑名單比對**：優先比對內政部 165 通報網址
* 🤖 **AI 智能評估**：灰色地帶網址與長文字，交給 Gemini 分析
* 💬 **LINE Bot（可選）**：若有設定 LINE 憑證，仍可繼續使用 Webhook

## 🛠️ 開發環境與套件
* **作業系統**：Windows / WSL (Ubuntu) / macOS
* **核心語言**：Python 3.12+
* **主要框架**：Flask, google-genai, python-dotenv
* **可選**：line-bot-sdk（只有要繼續用 LINE Bot 才需要填憑證）

## 🚀 本地開發安裝指南

### 1. 複製專案
```bash
git clone https://github.com/ccf540123/anti-scam-LINE-bot.git
cd anti-scam-LINE-bot
```

### 2. 建立並啟用虛擬環境
```bash
python3 -m venv env
source env/bin/activate  # Linux / macOS / WSL
# Windows 請使用: .\env\Scripts\activate
```

### 3. 安裝必要套件
```bash
pip install -r requirements.txt
```

### 4. 設定環境變數 (.env)
在專案根目錄建立 `.env` 檔案：

```env
# Website 模式至少需要一組 Gemini 金鑰
GEMINI_API_KEY_1=你的_Google_Gemini_API_Key
GEMINI_API_KEY_2=
GEMINI_API_KEY_3=

# 以下兩行只有要繼續使用 LINE Bot 才需要填
LINE_CHANNEL_SECRET=
LINE_CHANNEL_ACCESS_TOKEN=
```

### 5. 啟動服務
```bash
python3 app.py
```

瀏覽器打開：

```text
http://127.0.0.1:5001
```

貼上可疑文字或網址，按「開始分析」即可。

> 使用 `5001` 是為了避開 macOS AirPlay 常占用的 `5000` port。  
> Website 模式不需要 ngrok。

## 🌐 LINE Bot（可選）
如果你仍要測試 LINE Bot：

1. 填好 `LINE_CHANNEL_SECRET` 與 `LINE_CHANNEL_ACCESS_TOKEN`
2. 啟動 Flask
3. 再用 ngrok 把本機 5001 port 暴露出去：

```bash
ngrok http 5001
```

把 ngrok 的 `https://.../callback` 貼到 LINE Developers 的 Webhook URL。

Website 模式下可以完全不使用 ngrok。
