# -*- coding: utf-8 -*-
"""
AI 早报技能 v2.0 - GitHub可发布版
权重逻辑：机器之心 > 其他中文源 > 英文源
目标：每天最多20条，精选最重要新闻
"""
import os
import sys
import json
import re
import time
from datetime import datetime, timezone, timedelta
from typing import List, Dict

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ===================== 路径配置 =====================
SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SKILL_DIR, 'output')
CONFIG_DIR = os.path.join(SKILL_DIR, 'config')
DATA_DIR = os.path.join(SKILL_DIR, 'data')
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

# ===================== 六大分类 =====================
CATEGORIES = [
    ("1", "模型发布", "🤖"),
    ("2", "产品应用", "🚀"),
    ("3", "开发生态", "🛠️"),
    ("4", "资本动态", "💰"),
    ("5", "政策法规", "⚖️"),
    ("6", "前瞻传闻", "🔮"),
]

# 机器之心分类标签
JIQI_CATEGORIES = {
    "industry": "产品应用",
    "practice": "开发生态",
    "research": "模型发布",
    "opinion": "前瞻传闻",
}

# 分类关键词（辅助判断）
CATEGORY_KEYWORDS = {
    "1": ["模型", "LLM", "发布", "评测", "benchmark", "超越", "性能提升", "训练", "微调", "Base", "CustomVoice", "开源模型", "新模型", "参数量", "Scaling", "涌现"],
    "2": ["产品", "上线", "发布", "功能", "应用", "落地", "商业化", "用户", "App", "版本更新", "工具"],
    "3": ["API", "SDK", "开源", "框架", "工具", "库", "GitHub", "开发", "插件", "开发者", "LangChain"],
    "4": ["融资", "投资", "并购", "IPO", "上市", "估值", "亿美元", "资金", "收购", "CEO", "CTO", "高管"],
    "5": ["监管", "政策", "法规", "法律", "安全", "伦理", "审查", "隐私", "禁止", "限制"],
    "6": ["传闻", "爆料", "据说", "消息人士", "知情人士", "计划", "将推", "有望", "预计", "或将在"],
}

# AI 关键词（判断是否相关）
AI_KEYWORDS = [
    "AI", "人工智能", "LLM", "大模型", "ChatGPT", "GPT", "Claude", "Gemini",
    "机器学习", "深度学习", "神经网络", "Transformer", "Mamba", "Agent",
    "智能体", "RAG", "Embedding", "生成式", "AIGC", "多模态", "文生图",
    "文生视频", "自动驾驶", "具身智能", "机器人",
    "OpenAI", "Anthropic", "Google DeepMind", "Meta AI", "xAI",
    "字节", "阿里", "百度", "腾讯", "华为", "科大讯飞",
    "智谱", "月之暗面", "MiniMax", "阶跃星辰", "面壁智能",
    "模型", "推理", "Token", "训练", "涌现",
]


# ===================== 广告文过滤规则 =====================
# 多维度综合评分，不走关键词一票否决
# 基于对 7 个采集源、125 篇真实数据的分析

# 来源可信度（标题无强 AI 低可信来源直接过滤）
_AD_SOURCE_TRUST = {
    '机器之心':   1.0,
    '量子位':     0.9,
    'TechCrunch': 0.9,
    'The Verge':  0.8,
    '雷峰网':     0.3,
    '36氪':       0.2,
    '虎嗅':       0.1,
    'Anthropic':  1.0,
}

# 自家产品词（命中即过滤）
_AD_SELF_PROMO = {
    '36氪': [
        r'8点1氪', r'氪星晚报', r'36氪首发', r'36氪企业',
        r'社群.*招募', r'开放招募', r'36氪官方',
        r'幕启',  # 36氪专栏，仅图片无实质内容
    ],
}

# 高频广告品牌（标题中出现需进一步检查）
_AD_BRANDS = [
    '别克', '蔚来', '小鹏', 'Audi', '奥迪', '荣威', '赛力斯',
    '长城', '奇瑞', '智界', '星途', '至境', '理想',
    '极越', '极氪', '哪吒', '零跑', '东风日产',
    '荣耀', 'MagicBook', 'DingTalk', '钉钉',
    '追觅', '大疆',
]

# 品牌出现后，确认广告的词汇
_AD_BRAND_CONFIRM = [
    r'正式(发布|上市|开售)', r'行业首发', r'(全球|北京).*首秀',
    r'(北京|上海).*车展', r'(搭|装载).*(模型|大模型)',
    r'订单(环比|突破|提升|超)', r'(营收|净利润).*\d+.*亿',
    r'(增长|提升|上涨).*\d+%', r'(市占|销量|订单).*\d+%',
    r'(\d+万|\d+元)(起步|起)', r'全线.*(上市|发布|领跑)',
    r'多动力版本', r'能否站稳', r'全场景.*产品矩阵',
    r'(亮相|参展).*(车展|北京)', r'全场景.*落地',
    r'(开启|迈入).*(新|全面).*(阶段|时代|落地)',
]

# 产品发布通用模式（不依赖品牌名）
_AD_PRODUCT_PUB = [
    r'.*(发布|上市|开售).*(\d+元|\d+万|售价|定价)',
    r'.*系列.*(?:正式发布|上市)$',
    r'旗舰.*(?:轻薄本|游戏本|手机|平板)',
    r'(?:充电宝版|录音卡|手写笔|智能手表)',
    r'(?:多动力|多场景|全场景).*(?:上市|发布)',
    r'(?:告别|开启).*(?:革命|二次革命)',
]

# 合作推广模式
_AD_COOP_PROMO = [
    r'强强联手', r'.*牵手.*(?:阿里|腾讯|字节|百度|华为)',
    r'.*(?:达成|签署).*(?:战略|全面).*合作',
    r'.*(?:加大|扩大).*(?:投入|布局|投资)',
]

# 财报/数据报告模式
_AD_REPORT = [
    r'一季度.*营收', r'(上半年|全年).*营收',
    r'净利润.*\d+.*亿', r'同比.*增长.*\d+%',
    r'环比.*(增长|提升).*\d+%', r'订单.*(突破|环比).*\d+',
    r'(报告|数据).*(首发|显示|称)', r'年报|季报|财报',
]

# 活动宣传模式
_AD_EVENT = [
    r'.*年会.*闭幕', r'.*峰会.*闭幕', r'.*圆满闭幕',
    r'.*圆满收官', r'.*正式启动$',
]

# AI 保护词（防止误杀正常 AI 新闻）
_AD_AI_PROTECT = [
    r'\bACL\b.*\d{4}', r'\bCVPR\b.*\d{4}', r'\bNeurIPS\b.*\d{4}',
    r'\bICML\b.*\d{4}', r'\bICLR\b.*\d{4}', r'\bTPAMI\b',
    r'\bAAAI\b.*\d{4}', r'\bECCV\b.*\d{4}', r'\bEMNLP\b.*\d{4}',
    r'\bIJCAI\b.*\d{4}', r'开源', r'GitHub',
]

_AD_BRAND_RE = None  # 延迟编译
_AD_BRAND_CONFIRM_RE = None
_AD_PRODUCT_PUB_RE = None
_AD_COOP_PROMO_RE = None
_AD_REPORT_RE = None
_AD_EVENT_RE = None
_AD_AI_PROTECT_RE = None


def _compile_ad_rules():
    global _AD_BRAND_RE, _AD_BRAND_CONFIRM_RE, _AD_PRODUCT_PUB_RE
    global _AD_COOP_PROMO_RE, _AD_REPORT_RE, _AD_EVENT_RE, _AD_AI_PROTECT_RE
    _AD_BRAND_RE = re.compile('|'.join(_AD_BRANDS), re.IGNORECASE)
    _AD_BRAND_CONFIRM_RE = [re.compile(p) for p in _AD_BRAND_CONFIRM]
    _AD_PRODUCT_PUB_RE = [re.compile(p) for p in _AD_PRODUCT_PUB]
    _AD_COOP_PROMO_RE = [re.compile(p) for p in _AD_COOP_PROMO]
    _AD_REPORT_RE = [re.compile(p) for p in _AD_REPORT]
    _AD_EVENT_RE = [re.compile(p) for p in _AD_EVENT]
    _AD_AI_PROTECT_RE = [re.compile(p) for p in _AD_AI_PROTECT]


def is_advertisement(article: Dict) -> bool:
    """多维度综合评分广告文检测，>= 45 分判定为广告"""
    # 延迟编译正则
    if _AD_BRAND_RE is None:
        _compile_ad_rules()

    title = (article.get('title') or '').strip()
    source = article.get('source', '')
    trust = _AD_SOURCE_TRUST.get(source, 0.5)

    # 自家产品词检查（来源特定）
    if source in _AD_SELF_PROMO:
        for pat in _AD_SELF_PROMO[source]:
            if re.search(pat, title):
                return True  # 自家产品词：直接过滤

    score = 0

    # 品牌检测
    brand_match = _AD_BRAND_RE.search(title)
    if brand_match:
        brand = brand_match.group()
        for pat in _AD_BRAND_CONFIRM_RE:
            if pat.search(title):
                score += 40
                break
        if title.startswith(brand):
            score += 15

    # 产品发布通用模式
    for pat in _AD_PRODUCT_PUB_RE:
        if pat.search(title):
            score += 30
            break

    # 合作推广模式
    for pat in _AD_COOP_PROMO_RE:
        if pat.search(title):
            score += 25
            break

    # 来源可信度
    if trust <= 0.3:
        score += 25
    elif trust <= 0.5:
        score += 15

    # 财报/报告模式
    for pat in _AD_REPORT_RE:
        if pat.search(title):
            score += 20
            break

    # 活动宣传
    for pat in _AD_EVENT_RE:
        if pat.search(title):
            score += 25
            break

    # AI 保护（含强 AI 关键词的正常新闻降分）
    for pat in _AD_AI_PROTECT_RE:
        if pat.search(title):
            score -= 20
            break

    return score >= 45


def load_weights() -> dict:
    """加载学习权重"""
    weights_path = os.path.join(DATA_DIR, 'weights.json')
    defaults = {
        'source_weights': {
            '机器之心': 10,
            '36氪': 6,
            '雷峰网': 6,
            '量子位': 5,
            '虎嗅': 4,
            'The Verge': 4,
            'TechCrunch': 4,
            'Anthropic': 3,
        },
        'category_weights': {k: 1 for k, _, _ in CATEGORIES},
        'last_feedback': None,
    }
    if os.path.exists(weights_path):
        try:
            with open(weights_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, Exception):
            pass
    return defaults


def save_weights(weights: dict):
    """保存学习权重"""
    weights_path = os.path.join(DATA_DIR, 'weights.json')
    with open(weights_path, 'w', encoding='utf-8') as f:
        json.dump(weights, f, ensure_ascii=False, indent=2)


def apply_feedback(weights: dict, liked: List[str], disliked: List[str]):
    """根据大哥的反馈调整权重"""
    if not weights.get('source_weights'):
        return

    for title in liked:
        # 增加该来源权重
        for src in weights['source_weights']:
            if src in title:
                weights['source_weights'][src] = min(weights['source_weights'][src] + 1, 20)

    for title in disliked:
        # 降低该来源权重
        for src in weights['source_weights']:
            if src in title:
                weights['source_weights'][src] = max(weights['source_weights'][src] - 1, 1)

    weights['last_feedback'] = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')
    save_weights(weights)


def is_ai_news(article: Dict) -> bool:
    """判断是否是 AI 相关新闻"""
    title = (article.get('title') or '').lower()
    content = (article.get('content') or '').lower()
    tags = ' '.join(article.get('tags') or []).lower()
    combined = title + ' ' + content + ' ' + tags
    return any(kw.lower() in combined for kw in AI_KEYWORDS)


def classify_article(article: Dict) -> str:
    """将文章分类"""
    title = article.get('title', '')
    content = article.get('content', '')
    tags = ' '.join(article.get('tags') or [])
    combined = title + ' ' + content + ' ' + ' '.join(tags)

    # 机器之心自带分类
    jiqi_cat = article.get('category', '')
    if jiqi_cat in JIQI_CATEGORIES:
        for cat_id, cat_name, _ in CATEGORIES:
            if JIQI_CATEGORIES[jiqi_cat] == cat_name:
                return cat_id

    # 前瞻传闻（传闻关键词直接归类）
    rumor_kw = ["传闻", "爆料", "据说", "消息人士", "知情人士", "计划", "将推", "有望", "预计", "或将在"]
    if any(kw in combined for kw in rumor_kw):
        return "6"

    # 关键词匹配
    scores = {}
    for cat_id, cat_name, _ in CATEGORIES:
        keywords = CATEGORY_KEYWORDS.get(cat_id, [])
        score = sum(1 for kw in keywords if kw in combined)
        scores[cat_id] = score

    if scores:
        best = max(scores, key=scores.get)
        if scores[best] > 0:
            return best

    return "2"  # 默认产品应用


def get_importance(article: Dict, weights: dict) -> int:
    """计算重要性分数（综合权重）"""
    title = article.get('title', '')
    content = (article.get('content') or '')[:500]
    combined = title + ' ' + content

    # 基础分
    score = 0

    # 来源权重
    source = article.get('source', '')
    source_w = weights.get('source_weights', {}).get(source, 1)
    score += source_w

    # 关键词加分
    hot_kw = ["发布", "首发", "独家", "重磅", "世界首个", "全球首个", "最强", "超越", "刷新", "突破", "革命"]
    score += sum(3 for kw in hot_kw if kw in combined)

    # 星级转换（最高10分 → 3星）
    if score >= 12:
        return 3
    elif score >= 6:
        return 2
    else:
        return 1


def time_in_window(article: Dict) -> bool:
    """判断文章是否在24小时窗口内（每日播报不重复）"""
    now = datetime.now(timezone(timedelta(hours=8)))
    pub = article.get('publishedAt', '').strip()
    if not pub:
        return True  # 没有时间的保留

    try:
        if '/' in pub:
            dt = datetime.strptime(pub, '%Y/%m/%d %H:%M')
            dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
        else:
            import email.utils
            dt_tuple = email.utils.parsedate_tz(pub)
            if dt_tuple:
                # parsedate_tz 返回 UTC 偏移秒数，用实际偏移构造 dt
                tz_offset_sec = dt_tuple[9] if dt_tuple[9] is not None else 0
                dt = datetime(*dt_tuple[:6], tzinfo=timezone(timedelta(seconds=tz_offset_sec)))
            else:
                return True
        diff = now - dt
        return 0 <= diff.total_seconds() <= 86400  # 24小时
    except:
        return True  # 解析失败保留


def select_best_news(articles: List[Dict], weights: dict, max_items: int = 20) -> List[Dict]:
    """精选最重要新闻（权重排序 + 分类均衡）"""
    # 1. 过滤
    filtered = [a for a in articles if is_ai_news(a) and time_in_window(a)]
    print(f"  AI 过滤后: {len(filtered)} 篇")

    # 1.5 广告文过滤（采集阶段）
    before_ad = len(filtered)
    filtered = [a for a in filtered if not is_advertisement(a)]
    ad_removed = before_ad - len(filtered)
    if ad_removed > 0:
        print(f"  广告过滤: 移除 {ad_removed} 篇广告/软文")

    # 2. 计算重要性并排序
    for a in filtered:
        a['_importance'] = get_importance(a, weights)
        a['_cat'] = classify_article(a)

    # 3. 优先选机器之心高质量文章
    jiqi_articles = [a for a in filtered if a.get('source') == '机器之心']
    other_articles = [a for a in filtered if a.get('source') != '机器之心']

    # 机器之心最多取 12 条，其他源各补充
    selected = []
    jiqi_used = set()

    # 先选机器之心 ⭐⭐⭐（最多5条）
    top_jiqi = sorted([a for a in jiqi_articles if a['_importance'] == 3],
                      key=lambda x: x.get('publishedAt', ''), reverse=True)[:5]
    for a in top_jiqi:
        a['_selected_from'] = 'jiqi_top'
        selected.append(a)
        jiqi_used.add(a.get('title', ''))

    # 再选机器之心 ⭐⭐（最多7条）
    mid_jiqi = sorted([a for a in jiqi_articles if a['_importance'] == 2 and a.get('title', '') not in jiqi_used],
                     key=lambda x: x.get('publishedAt', ''), reverse=True)[:7]
    for a in mid_jiqi:
        a['_selected_from'] = 'jiqi_mid'
        selected.append(a)
        jiqi_used.add(a.get('title', ''))

    # 其他源补充（各2条 ⭐⭐）
    other_sources = {}
    for a in other_articles:
        src = a.get('source', '其他')
        if src not in other_sources:
            other_sources[src] = []
        other_sources[src].append(a)

    for src, arts in other_sources.items():
        if len(selected) >= max_items:
            break
        top_other = sorted([a for a in arts if a['_importance'] >= 2],
                          key=lambda x: x.get('publishedAt', ''), reverse=True)[:2]
        for a in top_other:
            if len(selected) >= max_items:
                break
            a['_selected_from'] = f'other_{src}'
            selected.append(a)

    # 如果还不够20条，放宽到 ⭐
    if len(selected) < 15:
        remaining_jiqi = [a for a in jiqi_articles if a.get('title', '') not in jiqi_used]
        for a in remaining_jiqi[:5]:
            if len(selected) >= max_items:
                break
            a['_selected_from'] = 'jiqi_fallback'
            selected.append(a)

    # 按时间排序
    selected.sort(key=lambda x: x.get('publishedAt', ''), reverse=True)

    print(f"  精选后: {len(selected)} 篇")
    for a in selected:
        src = a.get('source', '未知')
        stars = '⭐' * a['_importance']
        print(f"    {stars} [{src}] {a.get('title', '')[:40]}")

    return selected


def generate_report(articles: List[Dict], config: dict) -> str:
    """生成 Markdown 早报"""
    now = datetime.now(timezone(timedelta(hours=8)))
    date_str = now.strftime('%Y年%m月%d日')
    weekday = ['一', '二', '三', '四', '五', '六', '日'][now.weekday()]

    report = f"""# 🤖 AI 早报 | {date_str} 星期{weekday} {now.strftime('%H:%M')}

> 📡 精选 {len(articles)} 条 | 机器之心优先 | 学习进化版

---

"""

    # 按分类输出
    by_cat = {}
    for a in articles:
        cat = a.get('_cat', '2')
        if cat not in by_cat:
            by_cat[cat] = []
        by_cat[cat].append(a)

    for cat_id, cat_name, cat_emoji in CATEGORIES:
        items = by_cat.get(cat_id, [])
        if not items:
            continue

        report += f"## {cat_emoji} {cat_name}\n\n"

        for item in items:
            title = item.get('title', '无标题')
            url = item.get('url', '')
            time_str = item.get('publishedAt', '') or ''
            importance = item.get('_importance', 1)
            stars = '⭐' * importance
            source = item.get('source', '')
            content = item.get('content', '')
            summary = content[:120].replace('\n', ' ').strip() if content else ''

            report += f"**{stars} {title}**\n"
            report += f"> 🕐 {time_str}  |  📍 {source}\n"
            if summary:
                report += f">{summary}...\n"
            if url:
                report += f"[查看原文]({url})\n"
            report += "\n"

        report += "---\n\n"


    return report


def save_report(report: str) -> str:
    """保存早报到 temp/ 目录（干净版，无今日看点）"""
    now = datetime.now(timezone(timedelta(hours=8)))
    temp_dir = os.path.join(OUTPUT_DIR, 'temp')
    os.makedirs(temp_dir, exist_ok=True)
    filename = f"ai_daily_news_{now.strftime('%Y%m%d_%H%M')}.md"
    filepath = os.path.join(temp_dir, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(report)

    return filepath


def get_report_summary(articles: List[Dict]) -> str:
    """生成早报摘要（用于推送）"""
    now = datetime.now(timezone(timedelta(hours=8)))
    date_str = now.strftime('%m月%d日')

    lines = [f"🤖 **AI 早报 | {date_str}**\n"]

    by_cat = {}
    for a in articles:
        cat = a.get('_cat', '2')
        if cat not in by_cat:
            by_cat[cat] = []
        by_cat[cat].append(a)

    for cat_id, cat_name, cat_emoji in CATEGORIES:
        items = by_cat.get(cat_id, [])
        if not items:
            continue

        cat_lines = [f"\n**{cat_emoji} {cat_name}**\n"]
        for item in items[:5]:  # 每类最多5条
            title = item.get('title', '')[:35]
            stars = '⭐' * item.get('_importance', 1)
            url = item.get('url', '')
            if url:
                cat_lines.append(f"{stars} [{title}]({url})")
            else:
                cat_lines.append(f"{stars} {title}")

        lines.append('\n'.join(cat_lines[:6]))  # 每类最多6行

    lines.append(f"\n---\n📄 完整早报: `skills/ai-daily-news/output/latest.md`")
    return '\n'.join(lines)


def already_generated_today():
    """检查今天是否已生成过早报（防重复）"""
    now = datetime.now(timezone(timedelta(hours=8)))
    today_prefix = now.strftime('%Y%m%d')
    # 检查 output 目录下是否有今天的早报文件
    if os.path.exists(OUTPUT_DIR):
        for f in os.listdir(OUTPUT_DIR):
            if f.startswith(f'ai_daily_news_{today_prefix}_') and f.endswith('.md'):
                return True
    return False


def run_log(step, msg, start_time=None):
    """写入运行日志，同时打印到控制台"""
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    ts = now.strftime('%H:%M:%S')
    elapsed = ""
    if start_time is not None:
        elapsed = " [耗时 {:.1f}秒]".format(time.time() - start_time)
    line = "[{}] {}{}".format(ts, msg, elapsed)
    print(line)
    # 追加写到日志文件
    log_path = os.path.join(SKILL_DIR, 'run_log.txt')
    with open(log_path, 'a', encoding='utf-8') as lf:
        lf.write(line + '\n')


def main():
    import time as _time
    t0 = _time.time()
    tz = timezone(timedelta(hours=8))

    # 全局超时保护：采集阶段最多 90 秒，超时写日志并退出
    COLLECTION_TIMEOUT = 180
    _collection_timed_out = False

    def _check_timeout():
        nonlocal _collection_timed_out
        elapsed = _time.time() - t0
        if elapsed > COLLECTION_TIMEOUT:
            _collection_timed_out = True
            log_path = os.path.join(SKILL_DIR, 'run_log.txt')
            with open(log_path, 'a', encoding='utf-8') as lf:
                lf.write(f"\n[TIMEOUT] 全局采集超时 ({COLLECTION_TIMEOUT}秒)，脚本被终止\n")
            raise TimeoutError(f"采集阶段超过{COLLECTION_TIMEOUT}秒，自动终止")

    # 清空本次日志
    log_path = os.path.join(SKILL_DIR, 'run_log.txt')
    with open(log_path, 'w', encoding='utf-8') as lf:
        lf.write("=" * 60 + '\n')
        lf.write("AI 早报 v2 启动 | {}\n".format(datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S')))
        lf.write("=" * 60 + '\n')

    print("=" * 60)
    print("AI 早报 v2 启动 | {}".format(datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S')))
    print("=" * 60)

    # 防重复：今天已生成则跳过
    if already_generated_today():
        run_log('SKIP', '今天已生成过早报，跳过')
        print("[SKIP] 今天已生成过早报，退出")
        return None, None, None

    # 加载权重
    t1 = _time.time()
    run_log('INFO', '开始加载权重...')
    weights = load_weights()
    run_log('INFO', '权重加载完成', t1)

    # 采集新闻
    t1 = _time.time()
    sys.path.insert(0, SKILL_DIR)
    try:
        from news_sources import collect_all_news
    except Exception as e:
        run_log('ERROR', '无法导入 news_sources: {}'.format(e))
        return None, None, None

    print("\n[1/4] 采集新闻...")
    run_log('STEP', '=== [1/4] 采集新闻 ===')
    try:
        _check_timeout()  # 入场检查
        all_articles = collect_all_news()
        _check_timeout()  # 出场检查
    except TimeoutError:
        run_log('ERROR', '采集超时，已终止')
        print(f"\n[超时] 采集超过{COLLECTION_TIMEOUT}秒，已自动终止，防止cron被杀")
        # 写失败标记
        fail_flag = os.path.join(SKILL_DIR, 'run_failed.flag')
        with open(fail_flag, 'w', encoding='utf-8') as ff:
            ff.write(f'TIMEOUT_AT={datetime.now(tz).strftime("%H:%M:%S")}\n')
            ff.write(f'ELAPSED={_time.time()-t0:.1f}s\n')
        return None, None, None
    run_log('INFO', '采集完成，共 {} 篇'.format(len(all_articles)), t1)
    print("  总计: {} 篇".format(len(all_articles)))

    # 精选
    t1 = _time.time()
    print("\n[2/4] 精选新闻（权重排序）...")
    run_log('STEP', '=== [2/4] 精选新闻 ===')
    selected = select_best_news(all_articles, weights, max_items=20)
    run_log('INFO', '精选完成，选中 {} 条'.format(len(selected)), t1)

    # 生成早报
    t1 = _time.time()
    print("\n[3/4] 生成早报...")
    run_log('STEP', '=== [3/4] 生成早报 ===')
    report = generate_report(selected, {})
    filepath = save_report(report)
    run_log('INFO', '早报已保存: {}'.format(os.path.basename(filepath)), t1)

    # 生成摘要
    t1 = _time.time()
    print("\n[4/4] 生成摘要...")
    run_log('STEP', '=== [4/4] 生成摘要 ===')
    summary = get_report_summary(selected)
    run_log('INFO', '摘要生成完成', t1)

    print("\n✅ 完成！精选 {} 条".format(len(selected)))
    print("📄 完整版: {}".format(filepath))
    print("\n早报摘要预览：")
    print(summary)

    run_log('END', '脚本阶段全部完成！精选 {} 条，总耗时 {:.1f}秒'.format(len(selected), _time.time() - t0))
    # 写入完成标记（供 cron session AI 阶段记录）
    done_flag = os.path.join(SKILL_DIR, 'run_done.flag')
    with open(done_flag, 'w', encoding='utf-8') as df:
        df.write('SCRIPT_DONE\n')
        df.write('articles={}\n'.format(len(selected)))
        df.write('filepath={}\n'.format(filepath))
        df.write('duration={:.1f}\n'.format(_time.time() - t0))
        df.write('timestamp={}\n'.format(datetime.now(tz).strftime('%H:%M:%S')))

    return selected, filepath, summary


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--text-only', action='store_true', help='只生成文本早报，不触发语音播报')
    args = parser.parse_args()

    result = main()

    if result[0] is None:
        print("[ERROR] 采集失败或超时")
        sys.exit(1)

    selected, filepath, summary = result

    # 打印干净的早报摘要（方便 cron AI 直接发送）
    print("\n=== DAILY_REPORT_START ===")
    print(summary)
    print("=== DAILY_REPORT_END ===\n")

    # ✅ 音频生成已移至 generate_final.py（Phase 2），ai_daily_news.py 只负责文本
    print("[TEXT_ONLY] 早报文本已生成（音频由 generate_final.py 统一生成）")
    print(f"   MD: {filepath}")
    print(f"   TXT: {os.path.join(OUTPUT_DIR, 'latest.txt')}")
    sys.exit(0)
