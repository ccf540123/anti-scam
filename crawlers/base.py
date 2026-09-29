# crawlers/base.py
from dataclasses import dataclass


@dataclass
class Article:
    """統一的爬蟲文章資料結構"""
    url: str
    title: str
    content: str           # 完整正文（不含推文）
    published_at: str      # 發布時間（無法取得則空字串）
    source: str            # 例如 "ptt" 或 "dcard"
