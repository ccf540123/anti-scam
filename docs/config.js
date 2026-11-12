/*
  API 網址設定

  GitHub Pages 使用 Render 上的 anti-scam 服務。
  2026-11-12 確認 https://anti-scam-line-bot.onrender.com/api/health
  回傳 {"status":"ok"}。

  本機用 python app.py 測試、想打自己電腦上的後端時，
  把下面這行暫時改回空字串 ""。不要把 Gemini API Key 寫在這個檔案。
*/
window.API_BASE_URL = "https://anti-scam-line-bot.onrender.com";
