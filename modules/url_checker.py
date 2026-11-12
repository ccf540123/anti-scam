# modules/url_checker.py
import csv
import io
import os
import re
import requests
from urllib.parse import urlparse

# 知名官方網站白名單
WHITE_LIST = {
    "youtube.com", "youtu.be", "google.com", "gmail.com", 
    "facebook.com", "fb.me", "line.me", "instagram.com", 
    "github.com", "apple.com", "microsoft.com"
}

URL_PATTERN = re.compile(
    r"(https?://[^\s]+|www\.[^\s]+|[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/[^\s]*)?)"
)

LOCAL_165_CSV = "scam_165_urls.csv"  # 👈 定義本地實體 CSV 儲存檔名

def extract_urls(text):
    return URL_PATTERN.findall(text)

def detect_input_type(text):
    urls = extract_urls(text)
    if urls:
        return "url", urls
    return "text", []

def clean_url(url):
    url = url.strip().lower()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    try:
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path
        domain = domain.split("@")[-1]
        domain = domain.split(":")[0]
        if domain.startswith("www."):
            domain = domain[4:]
        return domain.strip("/")
    except Exception:
        return url

def extract_main_domain(url):
    url = url.strip().lower()
    if not url.startswith(('http://', 'https://')):
        url = 'http://' + url
    try:
        parsed_url = urlparse(url)
        netloc = parsed_url.netloc
        if netloc.startswith('www.'):
            netloc = netloc[4:]
        
        parts = netloc.split('.')
        if len(parts) >= 2:
            if parts[-2] in ['com', 'edu', 'gov', 'org', 'net']:
                return '.'.join(parts[-3:])
            return '.'.join(parts[-2:])
        return netloc
    except Exception:
        return clean_url(url)

def _load_local_165_snapshot(scam_urls):
    """下載失敗時只讀本地快照，不改寫檔案。"""
    if not os.path.exists(LOCAL_165_CSV):
        print("⚠️ 本地無歷史備份檔，改用空集合啟動。")
        return

    print(f"📂 [165 備份] 下載失敗，改讀本地快照 {LOCAL_165_CSV} ...")
    try:
        with open(LOCAL_165_CSV, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                url = row.get("normalized_url")
                if url:
                    scam_urls.add(url)
        print(f"✅ 成功從備份 CSV 恢復了 {len(scam_urls)} 筆詐騙黑名單！")
    except Exception as file_err:
        print(f"❌ 讀取本地備份 CSV 失敗: {file_err}，改用空集合啟動。")


def load_scam_urls(csv_url):
    """載入 165 名單到記憶體。

    伺服器啟動可嘗試下載，但無論成敗都不覆寫 scam_165_urls.csv。
    下載失敗時改讀 repo 裡的本地快照。
    """
    scam_urls = set()

    print("正在從網路下載 165 詐騙網址資料...")
    try:
        response = requests.get(csv_url, verify=False, timeout=10)
        response.raise_for_status()
        response.encoding = "utf-8-sig"

        file = io.StringIO(response.text)
        reader = csv.DictReader(file)
        for row in reader:
            raw_url = (row.get("WEBURL") or row.get("weburl") or row.get("網域") or row.get("網址") or "").strip()
            normalized = clean_url(raw_url)
            if normalized and normalized != "網址":
                scam_urls.add(normalized)

        print(f"165 詐騙網址資料載入完成，共 {len(scam_urls)} 筆（未覆寫 {LOCAL_165_CSV}）")
    except Exception as e:
        print(f"❌ 下載 165 資料失敗: {e}。")
        _load_local_165_snapshot(scam_urls)

    return scam_urls

# modules/url_checker.py

def check_if_user_input_matches_165(user_text, scam_urls_set):
    """
    精準交叉對比：檢查使用者輸入的內容中，是否包含 165 黑名單 (scam_165_urls.csv) 中的網址。
    如果命中，直接回傳該網址，否則回傳 None。
    """
    # 1. 提取出使用者輸入裡面的所有網址
    extracted_urls = extract_urls(user_text)
    
    if not extracted_urls:
        return None
        
    # 2. 逐一清洗並與 165 記憶體資料庫比對
    for raw_url in extracted_urls:
        normalized_user_url = clean_url(raw_url)
        
        # 只要清完後的網域有在 165 的 set 裡面
        if normalized_user_url in scam_urls_set:
            return raw_url  # 抓到了！直接回傳這個中獎的原始網址
            
    return None



def check_gray_zone_with_ai(user_text, url, call_api_func):
    """
    灰色地帶網址 AI 分析
    """
    print(f"[AI 啟動] 開始分析灰色地帶網址: {url}")
    prompt = f"""
    你是一名專業的網路安全防護與社交工程反詐騙專家。
    目前有一位 LINE 使用者收到了一則可疑訊息，該網址不在已知的官方白名單或政府通報黑名單中，屬於「灰色地帶」。
    
    請針對使用者收到的「完整內文」與「網址結構」進行多維度綜合評估。
    
    使用者收到的完整訊息：
    「{user_text}」
    
    訊息中提取出的可疑網址：
    「{url}」
    
    請嚴格依照以下格式回覆，不要包含任何 Markdown 標題符號（如 # 或 **），直接分段輸出即可：
    
    【風險評估等級】
    (請從 [安全 / 低風險 / 中風險 / 高風險] 中選擇一個最符合的標籤)
    
    【社交工程手法分析】
    (分析文字是否利用心理學盲點，例如：假冒官方、限時誘惑、製造焦慮恐慌、誘導提供簡訊驗證碼、假投資群組等。請簡短 2-3 句點出核心手法)
    
    【網址結構評估】
    (分析該網域長相，是否為亂碼組成的網域、短網址轉址、或者是刻意模仿大廠的釣魚網域)
    
    【給使用者的防範建議】
    (提供 1-2 點具體且溫慢的行動建議)
    """
    try:
        response = call_api_func(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"Gemini API 網址分析失敗: {e}")
        return (
            "⚠️ 【AI 系統暫時無法連線】\n"
            "由於此連結屬於未確認的灰色地帶，且 AI 評估機制暫時離線，"
            "強烈建議您不要點擊、不要輸入密碼或匯款，以保障個人資安。"
        )