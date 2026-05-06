# -*- coding: utf-8 -*-
"""
AI 新闻数据源采集模块 v2.0
支持多个数据源：机器之心API、量子位RSS、雷峰网、36氪、虎嗅镜像RSS、新智元、The Verge、TechCrunch
"""
import os
import sys
import time
import re
import requests
import threading
import queue
from datetime import datetime, timedelta
from typing import List, Dict, Optional

# Ensure UTF-8
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ===================== 全局配置 =====================
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate',
    'Connection': 'keep-alive',
}

REQUEST_TIMEOUT = 8
MAX_RETRIES = 1  # 减少重试，超时源直接跳过

# ===================== 工具函数 =====================

def safe_request(url: str, headers: dict = None, params: dict = None, timeout: int = REQUEST_TIMEOUT) -> Optional[requests.Response]:
    """安全的 HTTP 请求，带重试"""
    if headers is None:
        headers = HEADERS.copy()
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.get(url, headers=headers, params=params, timeout=timeout)
            if r.status_code == 200:
                return r
            elif r.status_code in [403, 451]:
                print(f"  [{url[:40]}...] {r.status_code}, skip")
                return None
        except Exception as e:
            print(f"  [{url[:40]}...] attempt {attempt+1} failed: {e}")
            time.sleep(1)
    return None


def extract_text(html: str, start: str, end: str) -> str:
    """简单提取 HTML 中的文本内容"""
    match = re.search(re.escape(start) + r'(.*?)' + re.escape(end), html, re.DOTALL)
    return match.group(1).strip() if match else ''


# ===================== 数据源采集函数 =====================

def collect_jiqizhixin(page: int = 1, per_page: int = 20) -> List[Dict]:
    """
    采集机器之心公开 API
    """
    url = 'https://www.jiqizhixin.com/api/article_library/articles.json'
    params = {'sort': 'time', 'page': page, 'per': per_page}
    articles = []

    r = safe_request(url, params=params)
    if not r:
        return articles

    try:
        data = r.json()
        if not data.get('success'):
            return articles

        for item in data.get('articles', []):
            slug = item.get('slug', '')
            articles.append({
                'id': item.get('id', ''),
                'title': item.get('title', ''),
                'url': f'https://www.jiqizhixin.com/articles/{slug}' if slug else '',
                'content': item.get('content', ''),
                'summary': item.get('content', '')[:200] if item.get('content') else '',
                'tags': item.get('tagList', []),
                'category': item.get('category', ''),
                'publishedAt': item.get('publishedAt', ''),
                'author': item.get('author', ''),
                'source': '机器之心',
                'coverImageUrl': item.get('coverImageUrl', ''),
            })
    except Exception as e:
        print(f"  Jiqizhixin parse error: {e}")

    return articles


def collect_qbitai() -> List[Dict]:
    """
    采集量子位 RSS（官方直发，稳定可靠）
    RSS: https://www.qbitai.com/rss
    """
    articles = []
    r = safe_request('https://www.qbitai.com/rss', timeout=10)
    if not r:
        return articles

    try:
        import feedparser
        feed = feedparser.parse(r.text)
        for entry in feed.entries[:20]:
            title = entry.get('title', '').strip()
            if not title:
                continue
            articles.append({
                'title': title,
                'url': entry.get('link', '') or entry.get('id', ''),
                'content': entry.get('summary', ''),
                'summary': (entry.get('summary', '') or '')[:200],
                'tags': ['量子位'],
                'publishedAt': entry.get('published', ''),
                'source': '量子位',
            })
    except Exception as e:
        print(f"  Qbitai RSS parse error: {e}")

    return articles


def collect_leiphone() -> List[Dict]:
    """
    采集雷峰网 RSS
    """
    articles = []
    r = safe_request('https://www.leiphone.com/feed')
    if not r:
        return articles

    try:
        import feedparser
        feed = feedparser.parse(r.text)
        for entry in feed.entries[:20]:
            articles.append({
                'title': entry.get('title', ''),
                'url': entry.get('link', ''),
                'content': entry.get('summary', ''),
                'summary': entry.get('summary', '')[:200],
                'tags': ['雷峰网'],
                'publishedAt': entry.get('published', ''),
                'source': '雷峰网',
            })
    except Exception as e:
        print(f"  Leiphone parse error: {e}")

    return articles


def collect_36kr() -> List[Dict]:
    """
    采集36氪 RSS
    """
    articles = []
    r = safe_request('https://36kr.com/feed')
    if not r:
        return articles

    try:
        import feedparser
        feed = feedparser.parse(r.text)
        for entry in feed.entries[:20]:
            articles.append({
                'title': entry.get('title', ''),
                'url': entry.get('link', ''),
                'content': entry.get('summary', ''),
                'summary': entry.get('summary', '')[:200],
                'tags': ['36氪'],
                'publishedAt': entry.get('published', ''),
                'source': '36氪',
            })
    except Exception as e:
        print(f"  36kr parse error: {e}")

    return articles


def collect_aiera() -> List[Dict]:
    """
    采集新智元首页爬虫
    """
    articles = []
    r = safe_request('https://aiera.com.cn', timeout=10)
    if not r:
        return articles

    try:
        html = r.text
        # 匹配文章链接: /YYYY/MM/DD/other/admin/数字/标题
        pattern = r'href="(https://aiera\.com\.cn/(\d{4})/(\d{2})/(\d{2})/other/admin/(\d+)/[^"]+)"[^>]*>([^<]{5,})</a>'
        matches = re.findall(pattern, html)
        seen_urls = set()
        for full_url, year, month, day, post_id, title in matches:
            # 跳过重复（每篇文章有标题和"点我查看"两个链接）
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)
            title = title.strip()
            if len(title) < 5:
                continue
            # 跳过"点我查看"开头的链接
            if title.startswith('点我查看'):
                continue
            articles.append({
                'title': title,
                'url': full_url,
                'content': '',
                'summary': '',
                'tags': ['新智元'],
                'publishedAt': f'{year}/{month}/{day}',
                'source': '新智元',
            })
    except Exception as e:
        print(f"  Aiera parse error: {e}")

    return articles


def collect_huxiu() -> List[Dict]:
    """
    采集虎嗅 RSS（通过镜像源，官方直发、无篡改、可回溯）
    优先使用镜像 RSS，失败时降级到官方源
    """
    articles = []
    # 优先：镜像 RSS（稳定不超时）
    r = safe_request('https://plink.anyfeeder.com/huxiu', timeout=10)
    if not r:
        # 降级：官方源
        r = safe_request('https://www.huxiu.com/rss/0.xml', timeout=8)
    if not r:
        return articles

    try:
        import feedparser
        feed = feedparser.parse(r.text)
        for entry in feed.entries[:20]:
            # 清理 CDATA 和 HTML 标签
            raw_title = entry.get('title', '')
            title = re.sub(r'<!\\[CDATA\\[|\\]\\]>', '', raw_title).strip()
            title = re.sub(r'<[^>]+>', '', title).strip()
            if not title:
                continue
            articles.append({
                'title': title,
                'url': entry.get('link', ''),
                'content': entry.get('summary', ''),
                'summary': entry.get('summary', '')[:200],
                'tags': ['虎嗅'],
                'publishedAt': entry.get('published', ''),
                'source': '虎嗅',
            })
    except Exception as e:
        print(f"  Huxiu parse error: {e}")

    return articles


def collect_verge() -> List[Dict]:
    """
    采集 The Verge Atom RSS
    """
    articles = []
    r = safe_request('https://www.theverge.com/rss/index.xml')
    if not r:
        return articles

    try:
        import feedparser
        feed = feedparser.parse(r.text)
        for entry in feed.entries[:15]:
            # 过滤 AI 相关
            title_lower = (entry.get('title') or '').lower()
            summary_lower = (entry.get('summary') or '').lower()
            combined = title_lower + summary_lower
            ai_keywords = ['ai', 'artificial intelligence', 'chatgpt', 'gpt', 'openai', 'google deepmind', 'meta ai', 'claude', 'anthropic']
            if any(kw in combined for kw in ai_keywords):
                articles.append({
                    'title': entry.get('title', ''),
                    'url': entry.get('link', ''),
                    'content': entry.get('summary', ''),
                    'summary': entry.get('summary', '')[:200],
                    'tags': ['The Verge'],
                    'publishedAt': entry.get('published', ''),
                    'source': 'The Verge',
                })
    except Exception as e:
        print(f"  The Verge parse error: {e}")

    return articles


def collect_techcrunch() -> List[Dict]:
    """
    采集 TechCrunch RSS
    """
    articles = []
    r = safe_request('https://techcrunch.com/feed/')
    if not r:
        return articles

    try:
        import feedparser
        feed = feedparser.parse(r.text)
        for entry in feed.entries[:15]:
            title_lower = (entry.get('title') or '').lower()
            summary_lower = (entry.get('summary') or '').lower()
            combined = title_lower + summary_lower
            ai_keywords = ['ai', 'artificial intelligence', 'chatgpt', 'gpt', 'openai', 'machine learning', 'startup', 'funding']
            if any(kw in combined for kw in ai_keywords):
                articles.append({
                    'title': entry.get('title', ''),
                    'url': entry.get('link', ''),
                    'content': entry.get('summary', ''),
                    'summary': entry.get('summary', '')[:200],
                    'tags': ['TechCrunch'],
                    'publishedAt': entry.get('published', ''),
                    'source': 'TechCrunch',
                })
    except Exception as e:
        print(f"  TechCrunch parse error: {e}")

    return articles


# ===================== 主采集函数 =====================

def _collect_with_timeout(func, result_q, error_q):
    """在子线程中执行采集函数，超时则抛异常"""
    try:
        articles = func()
        result_q.put(articles)
    except Exception as e:
        error_q.put(str(e))


def collect_all_news() -> List[Dict]:
    """
    从所有数据源采集新闻（并发+超时兜底）
    超时数据源自动跳过并写日志，不卡住整体流程
    """
    print("\n" + "=" * 50)
    print("开始采集 AI 新闻数据源")
    print("=" * 50)

    all_articles = []

    # 数据源列表：可靠快速源放前面，容易超时的放最后
    # 格式：(名称, 采集函数, 超时秒数)
    SOURCE_TIMEOUT = 15  # 每个数据源最多等这么久

    sources = [
        # 【第一梯队：国内快速源】
        ("🤖 机器之心",          lambda: collect_jiqizhixin(page=1, per_page=20), 15),
        ("🤖 机器之心 P2",       lambda: collect_jiqizhixin(page=2, per_page=20), 15),
        ("📰 36氪",              collect_36kr,  12),
        ("🔧 雷峰网",            collect_leiphone, 12),
        ("🔬 量子位RSS",         collect_qbitai, 10),
        ("🧠 新智元",            collect_aiera, 10),
        # 【第二梯队：国外源】
        ("🦁 虎嗅(镜像)",        collect_huxiu,  10),
        ("📡 The Verge",         collect_verge,  10),
        ("🚀 TechCrunch",       collect_techcrunch, 10),
    ]

    log_file = os.path.join(os.path.dirname(__file__), 'collection_log.txt')
    log_lines = []

    for name, func, timeout_sec in sources:
        print(f"\n正在采集: {name}...", end='', flush=True)
        result_q = queue.Queue()
        error_q = queue.Queue()
        t = threading.Thread(target=_collect_with_timeout, args=(func, result_q, error_q))
        t.daemon = True
        t.start()
        t.join(timeout=timeout_sec)

        if t.is_alive():
            # 超时了，记录并跳过
            msg = f"[{datetime.now().strftime('%H:%M:%S')}] 超时跳过: {name} (>{timeout_sec}秒)"
            print(f" ⏱️ 超时({timeout_sec}秒)，跳过")
            log_lines.append(msg)
            # 写入 run_log.txt（与 ai_daily_news.py 的日志一致）
            run_log_file = os.path.join(os.path.dirname(__file__), 'run_log.txt')
            with open(run_log_file, 'a', encoding='utf-8') as lf:
                lf.write(msg + '\n')
        else:
            try:
                articles = result_q.get_nowait()
                err = error_q.get_nowait() if not error_q.empty() else None
                if err:
                    print(f" ❌ {err}")
                    log_lines.append(f"[{datetime.now().strftime('%H:%M:%S')}] 错误: {name} - {err}")
                else:
                    print(f" ✅ {len(articles)}篇")
                    all_articles.extend(articles)
            except queue.Empty:
                print(f" ❌ 未知错误（队列为空）")

    # 统一写超时/错误日志
    if log_lines:
        with open(log_file, 'a', encoding='utf-8') as lf:
            lf.write(f"\n--- {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n")
            lf.write('\n'.join(log_lines) + '\n')

    # 去重（按标题）
    seen_titles = set()
    unique_articles = []
    for a in all_articles:
        title = a.get('title', '').strip()
        if title and title not in seen_titles:
            seen_titles.add(title)
            unique_articles.append(a)

    print(f"\n{'=' * 50}")
    skipped = len([l for l in log_lines if '超时' in l])
    print(f"采集完成！总计 {len(unique_articles)} 篇（去重后），跳过 {skipped} 个超时源")
    print(f"{'=' * 50}")

    return unique_articles


if __name__ == '__main__':
    # 测试采集
    articles = collect_all_news()
    print(f"\nTotal: {len(articles)}")
    for a in articles[:5]:
        print(f"  - {a.get('source')}: {a.get('title', '')[:50]}")
