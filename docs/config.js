/*
  API 網址設定

  1. 本機用 python app.py 開啟時：
     保持空字串 ""，前端會打同一個 Flask 的 /api/...

  2. GitHub Pages 正式使用時：
     等 Render 免費方案部署完成，且
     https://你的服務.onrender.com/api/health
     回傳 {"status":"ok"} 之後，只改下面那一行的空字串，
     換成那個真實網址（不含結尾斜線）。
     現在不要填範例網址或尚未證實可用的網址。

  注意：不要把 Gemini API Key 寫在這個檔案。
  金鑰只放在部署平台的環境變數 GEMINI_API_KEY_1。
*/
window.API_BASE_URL = "";
