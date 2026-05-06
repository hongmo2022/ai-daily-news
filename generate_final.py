# -*- coding: utf-8 -*-
"""
AI 早报第二步：生成最终 MD（含今日看点占位符）

读取 output/temp/ 最新干净 md → 查时段+节日 → 输出 HIGHLIGHTS_PROMPT
→ 写入 output/ 带占位符的最终 md

AI Agent 读取 HIGHLIGHTS_PROMPT 后用自身 LLM 生成今日看点，
替换 <!-- TODAY_HIGHLIGHTS --> 占位符，然后运行 broadcast.py 生成音频。

用法:
  python generate_final.py              # 处理 temp/ 最新文件
  python generate_final.py --temp-file output/temp/xxx.md  # 指定文件
"""
import os
import sys
import json
import re
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SKILL_DIR, 'output')
TEMP_DIR = os.path.join(OUTPUT_DIR, 'temp')
DATA_DIR = os.path.join(SKILL_DIR, 'data')

# ===================== 时段判断 =====================
def get_time_period():
    h = datetime.now().hour
    if 0 <= h < 3:   return "凌晨", "夜深了"
    if 3 <= h < 5:   return "黎明", "凌晨好"
    if 5 <= h < 7:   return "清晨", "清晨好"
    if 7 <= h < 9:   return "早上", "早上好"
    if 9 <= h < 12:  return "上午", "上午好"
    if 12 <= h < 14: return "中午", "中午好"
    if 14 <= h < 18: return "下午", "下午好"
    if 18 <= h < 19: return "傍晚", "傍晚好"
    if 19 <= h < 22: return "晚上", "晚上好"
    return "深夜", "夜深了"

# ===================== 节日判断 =====================
_SPRING_FESTIVAL = {
    2025: (1, 29),  2026: (2, 17),  2027: (2, 6),
    2028: (1, 26),  2029: (2, 13),  2030: (2, 3),
    2031: (1, 23),  2032: (2, 11),  2033: (1, 31),
    2034: (2, 19),  2035: (2, 8),
}

_LUNAR_OFFSETS = {
    '春节':    (0, 1, 0),
    '元宵节':  (0, 15, 0),
    '端午节':  (4, 5, 0),
    '中秋节':  (7, 15, 0),
    '重阳节':  (8, 9, 0),
}

_SOLAR_HOLIDAYS = {
    (1, 1): '元旦', (2, 14): '情人节', (3, 8): '妇女节',
    (4, 1): '愚人节', (4, 5): '清明节',
    (5, 1): '劳动节', (5, 4): '青年节', (6, 1): '儿童节',
    (7, 1): '建党节', (8, 1): '建军节', (9, 10): '教师节',
    (10, 1): '国庆节', (12, 25): '圣诞节',
}

_HOLIDAY_DURATION = {
    '春节': 7, '劳动节': 5, '国庆节': 7,
    '清明节': 3, '端午节': 3, '中秋节': 3, '元旦': 3,
}


def _calc_lunar_date(year, lunar_month, lunar_day):
    if year not in _SPRING_FESTIVAL:
        return None
    sm, sd = _SPRING_FESTIVAL[year]
    base = date(year, sm, sd)
    offset_days = (lunar_month - 1) * 30 + (lunar_day - 1)
    return base + timedelta(days=offset_days)


def _get_all_holidays_for_year(year):
    holidays = {}
    for name, (lm, ld, dur) in _LUNAR_OFFSETS.items():
        d = _calc_lunar_date(year, lm, ld)
        if d:
            duration = _HOLIDAY_DURATION.get(name, 1)
            holidays[name] = {'start': d, 'end': d + timedelta(days=duration - 1)}
    for (m, d), name in _SOLAR_HOLIDAYS.items():
        try:
            sd = date(year, m, d)
            duration = _HOLIDAY_DURATION.get(name, 1)
            holidays[name] = {'start': sd, 'end': sd + timedelta(days=duration - 1)}
        except ValueError:
            pass
    return holidays


def check_holiday():
    today = date.today()
    year = today.year
    holidays = _get_all_holidays_for_year(year)

    # 始终尝试从缓存补充节日数据（覆盖或补充锚点表）
    holiday_path = os.path.join(DATA_DIR, 'holiday_cache.json')
    if os.path.exists(holiday_path):
        try:
            with open(holiday_path, 'r', encoding='utf-8') as f:
                cache = json.load(f)
            for name, dates in cache.get(f'holidays_{year}', {}).items():
                if dates and len(dates) >= 2:
                    # holiday_cache.json 格式: ["结束日期", "开始日期"]
                    sd = datetime.strptime(dates[1], '%Y-%m-%d').date()
                    ed = datetime.strptime(dates[0], '%Y-%m-%d').date()
                    if sd <= ed:  # 防御：确保开始 <= 结束
                        holidays[name] = {'start': sd, 'end': ed}
        except Exception:
            pass

    for name, info in holidays.items():
        if info['start'] <= today <= info['end']:
            day_index = (today - info['start']).days + 1
            total_days = (info['end'] - info['start']).days + 1
            return (name, day_index, total_days)
    return None


# ===================== 从 md 提取新闻摘要 =====================
def extract_articles_summary(md_content):
    lines = md_content.split('\n')
    articles = []
    current_title = None

    for line in lines:
        m = re.match(r'\*\*⭐+\s+(.+?)\*\*', line)
        if m:
            current_title = m.group(1).strip()
            continue
        m = re.match(r'>(.+?)\.\.\.', line)
        if m and current_title:
            articles.append((current_title, m.group(1).strip()))
            current_title = None

    parts = []
    for i, (title, summary) in enumerate(articles[:15], 1):
        parts.append(f"{i}. {title} — {summary}" if summary else f"{i}. {title}")
    return '\n'.join(parts)


# ===================== 主流程 =====================
def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--temp-file', help='指定 temp/ 中的文件路径')
    args = ap.parse_args()

    # 1. 找到 temp/ 最新文件
    if args.temp_file:
        temp_path = args.temp_file
    else:
        if not os.path.exists(TEMP_DIR):
            print('[ERROR] temp/ 目录不存在，请先运行 ai_daily_news.py')
            sys.exit(1)
        temp_files = sorted(Path(TEMP_DIR).glob('ai_daily_news_*.md'))
        if not temp_files:
            print('[ERROR] temp/ 中没有找到早报文件')
            sys.exit(1)
        temp_path = str(temp_files[-1])

    print(f'[1/3] 读取: {os.path.basename(temp_path)}')
    with open(temp_path, 'r', encoding='utf-8') as f:
        md_content = f.read()

    # 2. 查时段+节日
    period_name, greeting = get_time_period()
    holiday_result = check_holiday()
    if holiday_result:
        holiday_name, holiday_day, holiday_total = holiday_result
        holiday_info = f' | 节日: {holiday_name}（假期第{holiday_day}天，共{holiday_total}天）'
    else:
        holiday_name = holiday_day = holiday_total = None
        holiday_info = ''
    print(f'[2/3] 时段: {period_name}（{greeting}）{holiday_info}')

    # 3. 提取新闻摘要
    articles_summary = extract_articles_summary(md_content)
    article_count = articles_summary.count('\n') + 1 if articles_summary else 0
    print(f'[3/3] 提取到 {article_count} 条新闻摘要')

    # 构建问候语
    if holiday_name:
        opening = f"{greeting}大哥，{holiday_name}假期第{holiday_day}天快乐！"
    else:
        opening = f"{greeting}大哥！"

    # 尝试用免费厂商自动生成今日看点
    auto_highlights = None
    try:
        from free_providers import generate_highlights as gen_hl
        auto_highlights = gen_hl(
            articles_summary=articles_summary,
            period_name=period_name,
            greeting=opening,
            holiday_name=holiday_name,
            holiday_day=holiday_day,
            holiday_total=holiday_total,
        )
    except Exception as e:
        print(f'[WARN] free_providers 异常: {e}')

    if auto_highlights:
        highlights_section = '## ⭐ 今日看点\n\n' + auto_highlights + '\n'
    else:
        highlights_section = '## ⭐ 今日看点\n\n<!-- TODAY_HIGHLIGHTS -->\n'

    # 输出 HIGHLIGHTS_PROMPT（仅当自动生成失败时，供 AI Agent 填写）
    if not auto_highlights:
        print()
        print('=== HIGHLIGHTS_PROMPT_START ===')
        print(f'请根据以下新闻列表生成一段"今日看点"总结。\n')
        print(f'时段：{period_name}')
        print(f'问候语：{opening}')
        if holiday_name:
            print(f'节日：{holiday_name}（假期第{holiday_day}天，共{holiday_total}天）')
        else:
            print(f'节日：无')
        print('要求：')
        print(f'- 开头用"{opening}"打招呼')
        print('- 用2-4句话概括今天最值得关注的新闻亮点')
        print('- 不要列序号，不要读标题，用总结性语言')
        print('- 风格：简洁、自然、有信息量，像朋友聊天一样')
        print('- 总字数控制在100-200字')
        print('- 绝对不要出现与当前时段不符的问候\n')
        print('今日新闻摘要：')
        print(articles_summary if articles_summary else '（无新闻摘要）')
        print()
        print('请直接输出总结文本。然后用 Edit 工具将 output/latest.md 中的')
        print('<!-- TODAY_HIGHLIGHTS --> 替换为你的总结。')
        print('=== HIGHLIGHTS_PROMPT_END ===')

    # 写入最终 md（自动生成或占位符）
    now = datetime.now(timezone(timedelta(hours=8)))
    final_content = md_content.rstrip()
    if final_content.endswith('---'):
        final_content += '\n\n' + highlights_section
    else:
        final_content += '\n\n---\n\n' + highlights_section

    filename = f"ai_daily_news_{now.strftime('%Y%m%d_%H%M')}.md"
    final_path = os.path.join(OUTPUT_DIR, filename)
    with open(final_path, 'w', encoding='utf-8') as f:
        f.write(final_content)

    latest_path = os.path.join(OUTPUT_DIR, 'latest.md')
    with open(latest_path, 'w', encoding='utf-8') as f:
        f.write(final_content)

    if auto_highlights:
        print(f'\n[OK] 最终版: {filename} + latest.md（免费厂商自动生成今日看点）')
        print(f'[NEXT] 运行 python broadcast.py 生成语音播报')
    else:
        print(f'\n[OK] 最终版: {filename} + latest.md（含占位符）')
        print(f'[NEXT] 请根据上方 HIGHLIGHTS_PROMPT 生成今日看点 → 替换占位符 → 运行 broadcast.py')

    # 清理临时文件
    try:
        os.remove(temp_path)
        print(f'[OK] 临时文件已删除: {os.path.basename(temp_path)}')
    except Exception as e:
        print(f'[WARN] 临时文件删除失败: {e}')


if __name__ == '__main__':
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    from datetime import datetime as _dt
    log_path = os.path.join(OUTPUT_DIR, 'generate_final.log')
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(f"[{_dt.now()}] generate_final.py 启动\n")
    main()
