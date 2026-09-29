# crawlers/ptt_crawler.py
import csv
import time
import requests
from bs4 import BeautifulSoup
from crawlers.base import Article  # 確保路徑正確

PTT_HEADERS = {"User-Agent": "Mozilla/5.0", "Cookie": "over18=1"}
DEFAULT_BOARDS = ["Bunco","Gossiping", "WomenTalk", "e-shopping", "creditcard", "Stock"]
DEFAULT_KEYWORDS = ["詐騙", "被騙", "投資詐騙", "交友詐騙", "假客服", "釣魚網站"]

def crawl_ptt_article(url):
    try:
        response = requests.get(url, headers=PTT_HEADERS, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        main = soup.select_one("#main-content")
        if not main: return ""
        for tag in main.select(".article-metaline, .article-metaline-right, .push"):
            tag.decompose()
        return main.get_text("\n", strip=True)[:500] # 限縮長度防爆 token
    except Exception:
        return ""

def crawl_ptt_search(board, keyword, pages=1):
    articles = []
    url = f"https://www.ptt.cc/bbs/{board}/search?q={keyword}"
    
    for _ in range(pages):
        try:
            response = requests.get(url, headers=PTT_HEADERS, timeout=10)
            if response.status_code != 200: break
            soup = BeautifulSoup(response.text, "html.parser")
            
            for entry in soup.select(".r-ent"):
                title_tag = entry.select_one(".title a")
                if not title_tag: continue
                
                title = title_tag.get_text(strip=True)
                article_url = "https://www.ptt.cc" + title_tag["href"]
                content = crawl_ptt_article(article_url)
                
                if title and content:
                    articles.append(Article(
                        url=article_url,
                        title=title,
                        content=content,
                        published_at="", # PTT 搜尋頁時間解析較繁瑣，暫留空或用當前時間
                        source="ptt"
                    ))
                time.sleep(0.5)
            
            # 尋找上一頁
            prev_button = soup.select_one("a.btn.wide:-soup-contains('上頁')")
            if not prev_button or not prev_button.get("href"): break
            url = "https://www.ptt.cc" + prev_button["href"]
        except Exception:
            break
    return articles

def fetch_all_ptt_scam(pages=1):
    """供外部 RAG 模組呼叫的統一接口"""
    all_articles = []
    for board in DEFAULT_BOARDS:
        for keyword in DEFAULT_KEYWORDS:
            print(f"📡 正在爬取 PTT: {board} / {keyword}")
            all_articles.extend(crawl_ptt_search(board, keyword, pages=pages))
    return all_articles