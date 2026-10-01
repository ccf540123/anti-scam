# crawlers/base.py
from dataclasses import dataclass, field


@dataclass
class Article:
    """統一的爬蟲文章資料結構（RAG 核心欄位在前）。"""

    url: str
    title: str
    content: str  # 完整正文（不含推文）
    published_at: str  # 發布時間（無法取得則空字串）
    source: str  # 例如 "ptt" 或 "dcard"

    # 以下為爬蟲 metadata；rag_searcher 可不使用這些欄位
    source_board: str = ""
    search_keyword: str = ""
    search_page: str = ""
    crawl_time: str = ""
    dedup_key: str = ""
    review_status: str = "unreviewed"
    possible_case_type: str = "unknown"
    author: str = field(default="", repr=False)
