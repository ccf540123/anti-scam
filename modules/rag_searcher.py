# modules/rag_searcher.py
import csv
import os
# 引入剛剛寫好的爬蟲們
from crawlers.ptt_crawler import fetch_all_ptt_scam
from crawlers.Dcard_crawler import DcardFraudCrawler

PTT_CSV = "ptt_scam_cases.csv"
DCARD_CSV = "dcard_scam_cases.csv"

def update_ptt_database():
    """更新本地 RAG 知識庫 (加入安全防護機制)"""
    print("🔄 [RAG 系統] 開始執行定時爬蟲任務...")
    
    # 1. 執行 PTT 爬蟲
    try:
        ptt_articles = fetch_all_ptt_scam(pages=1)
        if ptt_articles: # 👈 有抓到資料才寫入
            _save_to_csv(ptt_articles, PTT_CSV)
            print("  - PTT 知識庫更新成功")
        else:
            print("  - ⚠️ PTT 未回傳新資料，沿用舊有資料庫")
    except Exception as e:
        print(f"  - ❌ PTT 爬蟲崩潰: {e}，自動跳過並保護舊資料")

    # 2. 執行 Dcard 爬蟲
    try:
        dcard_crawler = DcardFraudCrawler()
        dcard_articles = dcard_crawler.fetch(limit=30)
        
        if dcard_articles: # 👈 只有在成功（非 403）且有資料時才覆蓋
            _save_to_csv(dcard_articles, DCARD_CSV)
            print("  - Dcard 知識庫更新成功")
        else:
            print("  - ⚠️ Dcard 觸發防爬蟲(403/429)，啟動保護機制：沿用本地既有資料庫")
    except Exception as e:
        print(f"  - ❌ Dcard 爬蟲崩潰: {e}，自動跳過並保護舊資料")
        
    print("✅ [RAG 系統] 知識庫定時任務執行完畢。")

def _save_to_csv(articles, filename):
    with open(filename, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(["title", "url", "content", "source", "published_at"])
        for art in articles:
            writer.writerow([art.title, art.url, art.content, art.source, art.published_at])

def search_related_cases(user_text, top_k=2):
    """
    這裡實作你們的 RAG 檢索邏輯。
    可以是簡單的關鍵字比對 (BM25)，或是用 Embedding 做向量搜尋。
    同時讀取 ptt_scam_cases.csv 與 dcard_scam_cases.csv 來尋找最相似的案例。

    必要欄位：title, url, content, source
    （CSV 若含 source_board / search_keyword 等額外欄位會被忽略，不影響檢索）
    """
    matched_cases = []
    
    # 範例：簡單讀取兩個 CSV 做關鍵字命中
    for csv_file in [PTT_CSV, DCARD_CSV]:
        if not os.path.exists(csv_file): continue
        with open(csv_file, "r", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            for row in reader:
                # 如果使用者說的話裡面，包含了 CSV 標題裡的某些字
                # (實際專案建議用向量相似度，這邊示範基本邏輯)
                title = row.get("title") or ""
                source = row.get("source") or ""
                url = row.get("url") or ""
                content = row.get("content") or ""
                if any(kw in title for kw in ["詐騙", "騙", "投資"] if kw in user_text):
                    matched_cases.append({
                        "title": f"[{source.upper()}] {title}",
                        "url": url,
                        "content": content
                    })
                if len(matched_cases) >= top_k:
                    break
    return matched_cases[:top_k]