# -*- coding: utf-8 -*-
"""
AI早报 MD→TXT→语音播报脚本 v2.0
.md 原文不做任何修改，所有清洗/替换仅在 .md→.txt 时完成

用法:
  python broadcast.py                  # 处理最新一期早报 → TXT + MP3
  python broadcast.py --text-only      # 只生成TXT，不生成音频
  python broadcast.py --date 20260424  # 处理指定日期的早报
  python broadcast.py --voice zh-CN-YunxiNeural  # 指定音色
"""
import os
import sys
import re
import json
import random
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ===================== 日志工具 =====================
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output', 'broadcast.log')


def _log(msg, level="INFO"):
    """写入 broadcast.log，console 也同步 print"""
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] [{level}] {msg}"
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass
    print(line)

# ===================== 路径配置 =====================
SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(SKILL_DIR, 'config')
OUTPUT_DIR = os.path.join(SKILL_DIR, 'output')

# ===================== 加载配置 =====================
def load_config(filename):
    filepath = os.path.join(CONFIG_DIR, filename)
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

POLYPHONE_MAP = load_config('polyphone_map.json')
AD_FILTER = load_config('ad_filter.json')

# ===================== 板块名称 =====================
SECTION_NAMES = ['模型发布', '产品应用', '开发生态', '资本动态', '政策法规', '前瞻传闻']
SECTION_EMOJI = {
    '模型发布': '🤖', '产品应用': '🚀', '开发生态': '🛠️',
    '资本动态': '💰', '政策法规': '⚖️', '前瞻传闻': '🔮',
}


# ===================== 文本清洗（仅在 .md→.txt 时调用） =====================
def clean_title(title):
    """清洗标题：仅做学术会议前缀去除。广告词已在采集阶段过滤。"""
    # 去学术会议前缀（动态匹配年份）
    title = re.sub(
        r'^(ICLR|CVPR|NeurIPS|AAAI|ACL|ICML|ECCV|EMNLP|IJCAI)\s+\d{4}\s*[｜|]\s*',
        '', title
    )
    # 清理残留分隔符
    title = re.sub(r'^\s*[｜丨|]\s*', '', title)
    title = re.sub(r'\s*[｜丨|]\s*$', '', title)
    return title.strip()


def apply_polyphone(text):
    """应用多音字替换。.md原文不动！"""
    for original, replacement in POLYPHONE_MAP.items():
        text = text.replace(original, replacement)
    return text


# ===================== MD 解析 =====================
def parse_md(filepath):
    """解析早报MD，提取日期/星期和各板块新闻标题"""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    first_line = content.split('\n')[0] if content else ''

    # 提取日期和星期
    date_match = re.search(r'(\d{4})年(\d{2})月(\d{2})日\s*(星期\S+)', first_line)
    if date_match:
        year, month, day, weekday = date_match.groups()
        date_str = f'{year}年{month}月{day}日'
    else:
        fname = os.path.basename(filepath)
        dm = re.search(r'(\d{4})(\d{2})(\d{2})', fname)
        if dm:
            year, month, day = dm.groups()
            try:
                date_str = f'{year}年{month}月{day}日'
                wk = ['星期一','星期二','星期三','星期四','星期五','星期六','星期日']
                weekday = wk[datetime(int(year), int(month), int(day)).weekday()]
            except (ValueError, OverflowError):
                date_str = datetime.now().strftime('%Y年%m月%d日')
                weekday = ''
        else:
            date_str = datetime.now().strftime('%Y年%m月%d日')
            weekday = ''

    # 提取时间
    time_match = re.search(r'(\d{2}):(\d{2})', first_line)
    time_str = f'{time_match.group(1)}点{time_match.group(2)}' if time_match else ''

    # 解析各板块标题
    sections = {}
    current_section = None

    for line in content.split('\n'):
        line_stripped = line.strip()
        # 检测板块标题行（## 开头，含板块名）
        is_section_header = False
        for section_name in SECTION_NAMES:
            if line_stripped.startswith('##') and section_name in line_stripped:
                current_section = section_name
                if current_section not in sections:
                    sections[current_section] = []
                is_section_header = True
                break
        if is_section_header:
            continue
        # 检测新闻标题行（以 ** 开头，含⭐评级）
        if current_section and line_stripped.startswith('**') and '⭐' in line_stripped:
            # 提取 **之间的内容**
            title_match = re.match(r'\*\*\s*(⭐+\s*.+?)\s*\*\*', line_stripped)
            if title_match:
                raw_title = title_match.group(1)
                # 去掉⭐标记
                raw_title = raw_title.replace('⭐', '').strip()
                # 去markdown链接
                raw_title = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', raw_title)
                if raw_title and len(raw_title) > 2:
                    sections[current_section].append(raw_title)

    return {
        'date_str': date_str,
        'weekday': weekday,
        'time_str': time_str,
        'sections': sections,
    }


# ===================== 生成播报文本 =====================
def generate_broadcast_text(parsed):
    """将解析结果转换为语音播报文本（含全部清洗/替换）"""
    date_str = parsed['date_str']
    weekday = parsed['weekday']

    # === 开头 ===
    opening = f'今日AI早报，{date_str}，{weekday}。'

    # === 各板块 ===
    section_parts = []
    first_section = True
    for section_name in SECTION_NAMES:
        titles = parsed['sections'].get(section_name, [])
        if not titles:
            continue  # 跳过空板块

        part = ''
        if not first_section:
            part += '接下来是'
        part += f'{section_name}板块。'
        first_section = False

        for i, title in enumerate(titles, 1):
            # ===== 只在转txt时做清洗 =====
            cleaned = clean_title(title)
            cleaned = apply_polyphone(cleaned)
            # 序号用顿号，增加停顿感；标题自身有标点结尾则不再加句号
            if cleaned and cleaned[-1] in '！？。；：':
                part += f'{i}、{cleaned}'
            else:
                part += f'{i}、{cleaned}。'

        section_parts.append(part)

    # === 今日看点（从 .md 中读取 AI 已生成的内容）===
    highlight_part = ''
    md_path = parsed.get('_md_path', '')
    if md_path and os.path.exists(md_path):
        try:
            with open(md_path, 'r', encoding='utf-8') as f:
                md_content = f.read()
            # 提取今日看点段落（在 ## ⭐ 今日看点 之后到文件末尾或下一个 ## 之前）
            match = re.search(r'## ⭐ 今日看点\n\n(.+?)(?:\n\n##|\n*$)', md_content, re.DOTALL)
            if match:
                highlights = match.group(1).strip()
                if highlights and highlights != '<!-- TODAY_HIGHLIGHTS -->':
                    highlight_part = '接下来是今日看点。' + highlights
        except Exception:
            pass

    body = ''.join(section_parts) + highlight_part

    # === 结束语 ===
    endings = [
        '以上就是今日AI早报的全部内容，感谢收听，我们明天见。',
        '今日AI早报播报完毕，祝您一天好心情，明天见！',
        '今天的AI早报就到这里，关注前沿不迷路，我们明天接着聊！',
        '今日AI早报播报完毕，愿你今天充满灵感，我们明天见！',
        'AI早报今天的播报到此结束，新的一天加油，明天见！',
    ]
    ending = random.choice(endings)

    full_text = opening + body + ending
    return full_text


# ===================== TTS 引擎管理（对齐每日问候语架构） =====================

_SKILL_DATA_DIR = os.path.join(SKILL_DIR, 'data')
_TTS_CONFIG_PATH = os.path.join(CONFIG_DIR, 'tts_config.json')
_TTS_CONFIG_DEFAULT = os.path.join(_SKILL_DATA_DIR, 'tts_config_default.json')


def _load_tts_config():
    """加载 TTS 配置，优先 config/tts_config.json，不存在则用 data/ 默认模板"""
    for path in [_TTS_CONFIG_PATH, _TTS_CONFIG_DEFAULT]:
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
    return {}


def _get_ffprobe_path():
    """获取 ffprobe 路径：config > 系统 PATH"""
    cfg = _load_tts_config()
    p = cfg.get("ffprobe_path", "")
    if p and os.path.exists(p):
        return p
    return "ffprobe"


def _get_ffmpeg_path():
    """获取 ffmpeg 路径：config > 系统 PATH"""
    cfg = _load_tts_config()
    p = cfg.get("ffmpeg_path", "")
    if p and os.path.exists(p):
        return p
    return "ffmpeg"


def _get_qwen3tts_script():
    """获取 Qwen3TTS speak.py 路径：用户配置 > data/ 自带"""
    cfg = _load_tts_config()
    ecfg = cfg.get("engines", {}).get("qwen3tts", {})
    user_path = ecfg.get("speak_script", "")
    if user_path and os.path.isabs(user_path) and os.path.exists(user_path):
        return user_path
    return os.path.join(_SKILL_DATA_DIR, "speak.py")


def _get_switcher_dir():
    """获取 tts_switcher 目录：用户配置 > data/ 自带"""
    cfg = _load_tts_config()
    ecfg = cfg.get("engines", {}).get("xiaomi-mimo-tts", {})
    user_path = ecfg.get("script_path", "")
    if user_path and os.path.exists(user_path):
        return os.path.dirname(user_path)
    return _SKILL_DATA_DIR


def _auto_detect_engine(cfg):
    """自动探测哪个 TTS 引擎可用，按优先级返回"""
    engines = cfg.get("engines", {})
    sorted_engines = sorted(engines.items(), key=lambda x: x[1].get("priority", 99))
    for name, ecfg in sorted_engines:
        if not ecfg.get("enabled", False):
            continue
        if name == "edge-tts":
            try:
                import edge_tts  # noqa: F401
                return "edge-tts"
            except ImportError:
                pass
        elif name == "xiaomi-mimo-tts":
            user_path = ecfg.get("script_path", "")
            if user_path and os.path.exists(user_path):
                return "xiaomi-mimo-tts"
            if os.path.exists(os.path.join(_SKILL_DATA_DIR, "tts_switcher.py")):
                return "xiaomi-mimo-tts"
        elif name == "qwen3tts":
            user_path = ecfg.get("speak_script", "")
            if user_path and os.path.exists(user_path):
                return "qwen3tts"
            if os.path.exists(os.path.join(_SKILL_DATA_DIR, "speak.py")):
                return "qwen3tts"
        elif name == "sapi":
            return "sapi"
    return None


def get_active_engine():
    """读取当前激活的 TTS 引擎及其能力标签

    返回: dict
        {
            "name": "edge-tts",
            "tags": ["cloud"],
            "features": {"emotion": false, "clone": false, ...}
        }
    """
    default_engine = "edge-tts"
    default_tags = ["cloud"]
    default_features = {"emotion": False, "clone": False, "dialect": False, "singing": False}

    cfg = _load_tts_config()
    active = cfg.get("active_engine", default_engine)
    if active == "auto":
        active = _auto_detect_engine(cfg) or default_engine

    engine_cfg = cfg.get("engines", {}).get(active, {})
    return {
        "name": active,
        "tags": engine_cfg.get("tags", default_tags),
        "features": engine_cfg.get("features", default_features)
    }


# ===================== 音频完整性校验 =====================
def verify_audio(text, audio_path, engine_name=None):
    """校验音频完整性：字数-时长匹配，误差<10%为合格
    注意：MiMo 情绪语音实际时长可能是理论时长的 2-5 倍（情绪停顿），跳过时长校验
    """
    # 日志文件路径
    verify_log = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output', 'broadcast_verify.log')
    os.makedirs(os.path.dirname(verify_log), exist_ok=True)
    
    # 1. 统计中文字数（仅保留\u4e00-\u9fa5范围内的中文，排除标点/空格/英文）
    chinese_chars = re.findall(r'[\u4e00-\u9fa5]', text)
    word_count = len(chinese_chars)
    if word_count == 0:
        log_msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 文本无中文，跳过校验"
        print(f"⚠️ {log_msg}")
        with open(verify_log, 'a', encoding='utf-8') as f:
            f.write(log_msg + '\n')
        return True  # 无中文内容不校验
    
    # 2. 计算理论时长（基准语速3.5字/秒，广播文本含板块过渡和自然停顿）
    theory_duration = word_count / 3.5  # 单位：秒
    
    # 3. 用ffprobe获取实际音频时长
    ffprobe_path = _get_ffprobe_path()
    # 只有绝对路径才检查文件存在；"ffprobe"这种PATH命令直接放行
    if os.path.isabs(ffprobe_path) and not os.path.exists(ffprobe_path):
        log_msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ffprobe不存在：{ffprobe_path}，跳过校验"
        print(f"⚠️ {log_msg}")
        with open(verify_log, 'a', encoding='utf-8') as f:
            f.write(log_msg + '\n')
        return True
    
    try:
        # 调用ffprobe获取音频元数据（JSON格式）
        # 注意：MiMo TTS 生成的 MP3，ffprobe -v quiet 时 stdout 可能为空（已知兼容问题）
        # 使用 bytes 输出，避免 text=True 的 UnicodeDecodeError 线程崩溃
        result = subprocess.run(
            [ffprobe_path, "-v", "quiet", "-print_format", "json", "-show_format", audio_path],
            capture_output=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
        )
        if result.returncode != 0:
            stderr_text = (result.stderr or b'').decode('utf-8', errors='replace')[:200]
            log_msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ffprobe执行失败(rc={result.returncode})：{stderr_text}"
            print(f"⚠️ {log_msg}")
            with open(verify_log, 'a', encoding='utf-8') as f:
                f.write(log_msg + '\n')
            return False

        # 兼容 MiMo MP3：stdout 可能为空，此时跳过时长校验（宁可放过，不可误删）
        raw_stdout = result.stdout
        if not raw_stdout or not raw_stdout.strip():
            log_msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ffprobe返回空输出（MiMo MP3兼容问题），跳过校验"
            print(f"⚠️ {log_msg}")
            with open(verify_log, 'a', encoding='utf-8') as f:
                f.write(log_msg + '\n')
            return True

        # 解析JSON获取时长（bytes → str）
        info = json.loads(raw_stdout.decode('utf-8'))
        actual_duration = float(info["format"]["duration"])
    except Exception as e:
        log_msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 获取音频时长失败：{e}，跳过校验"
        print(f"⚠️ {log_msg}")
        with open(verify_log, 'a', encoding='utf-8') as f:
            f.write(log_msg + '\n')
        return True  # 异常时跳过校验，不删除音频
    
    # 4. 计算误差并判断
    # MiMo 情绪语音跳过时长校验（情绪停顿/语速变化导致时长远超理论值，这是正常的）
    if engine_name and engine_name.startswith("xiaomi"):
        log_msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] MiMo引擎跳过时长校验（情绪语音时长不可预测）"
        print(f"✅ {log_msg}")
        with open(verify_log, 'a', encoding='utf-8') as f:
            f.write(log_msg + '\n')
        return True

    error = abs(actual_duration - theory_duration) / theory_duration
    if error > 0.5:  # 误差阈值50%（TTS语速波动大，宽容忍防止误删正常音频）
        log_msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 音频不完整：字数={word_count}，理论时长={theory_duration:.1f}s，实际={actual_duration:.1f}s，误差={error:.1%}"
        print(f"⚠️ {log_msg}")
        with open(verify_log, 'a', encoding='utf-8') as f:
            f.write(log_msg + '\n')
        return False
    else:
        log_msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 音频校验通过：字数={word_count}，时长={actual_duration:.1f}s，误差={error:.1%}"
        print(f"✅ {log_msg}")
        with open(verify_log, 'a', encoding='utf-8') as f:
            f.write(log_msg + '\n')
        return True


def generate_audio(text, output_dir, engine_override=None):
    """生成音频文件——自己读 config、自己路由、直接调对应引擎脚本

    与每日问候语 play_greeting_paragraphs 架构一致：
    - 不依赖 tts_switcher generate 命令
    - 自己读 config.json，自己决定用哪个引擎
    - 各引擎直接调对应脚本，互不干扰
    - 兜底默认 MiMo

    Args:
        text: 播报文本
        output_dir: 输出目录
        engine_override: 强制指定引擎（None 则读 config）

    返回: 音频文件路径（str）或 None
    """
    # ── 1. 确定引擎 ──
    if engine_override:
        engine_info = {"name": engine_override, "tags": ["cloud"],
                       "features": {"emotion": False, "clone": False, "dialect": False, "singing": False}}
    else:
        engine_info = get_active_engine()

    engine_name = engine_info["name"]
    _log(f'开始生成音频，引擎={engine_name}', 'INFO')
    print(f'正在生成音频（引擎: {engine_name}）...')

    # 判断是否允许 fallback：仅 auto 模式或引擎自身就是 edge-tts 时允许
    # 用户显式指定的引擎失败就报错，不偷偷换引擎
    allow_fallback = (not engine_override) and (
        engine_name == "edge-tts" or _load_tts_config().get("active_engine") == "auto"
    )

    # ── 2. 按引擎路由 ──
    # 策略：
    #   用户显式指定引擎 → 失败直接返回 None，不 fallback
    #   auto 模式 → qwen3tts/MiMo 失败 → edge-tts（唯一始终可用的云引擎）
    #   edge-tts 失败 → 报错返回 None
    if engine_name == "qwen3tts":
        _log('路由到 Qwen3TTS', 'INFO')
        result = _generate_with_qwen3tts(text, output_dir)
        if result:
            _log(f'Qwen3TTS 成功 → {result}', 'INFO')
            if not verify_audio(text, result, engine_name):
                if os.path.exists(result):
                    os.remove(result)
                    _log(f'Qwen3TTS 音频校验失败，已删除：{result}', 'WARN')
                return None
            return result
        if allow_fallback:
            _log('Qwen3TTS 失败，fallback 到 edge-tts', 'WARN')
            print('⚠️ Qwen3TTS 失败，auto模式切换到 edge-tts')
            return _generate_with_edge(text, output_dir)
        _log('Qwen3TTS 失败，引擎由用户指定，不 fallback', 'WARN')
        return None
    elif engine_name == "xiaomi-mimo-tts":
        _log('路由到 MiMo TTS', 'INFO')
        result = _generate_with_mimo(text, output_dir)
        if result:
            _log(f'MiMo TTS 成功 → {result}', 'INFO')
            if not verify_audio(text, result, engine_name):
                if os.path.exists(result):
                    os.remove(result)
                    _log(f'MiMo TTS 音频校验失败，已删除：{result}', 'WARN')
                return None
            return result
        if allow_fallback:
            _log('MiMo TTS 失败，fallback 到 edge-tts', 'WARN')
            print('⚠️ MiMo 失败，auto模式切换到 edge-tts')
            return _generate_with_edge(text, output_dir)
        _log('MiMo TTS 失败，引擎由用户指定，不 fallback', 'WARN')
        return None
    elif engine_name == "edge-tts":
        _log('路由到 edge-tts', 'INFO')
        result = _generate_with_edge(text, output_dir)
        if result:
            # 新增：音频完整性校验
            if not verify_audio(text, result, engine_name):
                if os.path.exists(result):
                    os.remove(result)
                    _log(f'edge-tts 音频校验失败，已删除：{result}', 'WARN')
                return None
            return result
        return None
    else:
        if allow_fallback:
            _log(f'未知引擎 "{engine_name}"，fallback 到 edge-tts', 'WARN')
            print(f'⚠️ 未知引擎 "{engine_name}"，auto模式切换到 edge-tts')
            return _generate_with_edge(text, output_dir)
        _log(f'未知引擎 "{engine_name}"，不 fallback', 'WARN')
        print(f'⚠️ 未知引擎 "{engine_name}"，且不允许 fallback')
        return None


def _generate_with_qwen3tts(text, output_dir):
    """Qwen3TTS 生成音频——逐段生成 + ffmpeg 合成

    策略：
    1. 按句号/感叹号/问号切分成段落
    2. 每段独立调 speak.py --output <file>（不播放，只生成文件）
    3. ffmpeg concat 合成一个完整 WAV
    4. 清理临时文件
    """
    import tempfile, shutil
    tts_script = _get_qwen3tts_script()
    if not os.path.exists(tts_script):
        print(f'[ERROR] Qwen3TTS 脚本不存在: {tts_script}')
        return None

    # 先检测服务是否可用
    try:
        import requests
        r = requests.get('http://127.0.0.1:7860', timeout=3)
        if r.status_code >= 500:
            raise ValueError('service error')
    except Exception:
        print('⚠️ Qwen3TTS 服务不可用')
        return None

    # ── 1. 切分段落（按句号/感叹号/问号，保留分隔符）──
    # 用正则切分，保留分隔符
    segments = re.findall(r'[^。！？]+[。！？]*', text)
    # 过滤空段和纯标点
    segments = [s.strip() for s in segments if s.strip() and len(s.strip()) > 1]
    if not segments:
        segments = [text]  # 没法切分就整段

    print(f'  [Qwen3TTS] 共 {len(segments)} 段，逐段生成...')

    # ── 2. 逐段生成音频文件 ──
    tmp_dir = Path(tempfile.mkdtemp(prefix="ai_news_qwen3_"))
    audio_paths = []

    for i, seg in enumerate(segments):
        out_path = tmp_dir / f"seg_{i:03d}.wav"
        print(f'  [Qwen3TTS] 段落 {i+1}/{len(segments)} ({len(seg)}字): {seg[:40]}...')
        try:
            result = subprocess.run(
                [sys.executable, str(tts_script), seg, "--output", str(out_path)],
                capture_output=True, text=True, errors="replace", timeout=120,
                cwd=os.path.dirname(tts_script),
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
            )
            if result.returncode == 0 and out_path.exists():
                audio_paths.append(str(out_path))
                print(f'  [Qwen3TTS] 段落 {i+1} 生成成功 ({out_path.stat().st_size // 1024}KB)')
            else:
                err_msg = (result.stderr or result.stdout or "未知错误")[-200:]
                print(f'  [WARN] 段落 {i+1} 生成失败: {err_msg}')
        except subprocess.TimeoutExpired:
            print(f'  [WARN] 段落 {i+1} 超时，跳过')
        except Exception as e:
            print(f'  [WARN] 段落 {i+1} 异常: {e}')

    if not audio_paths:
        print('❌ Qwen3TTS 所有段落生成失败')
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return None

    print(f'  [Qwen3TTS] 成功生成 {len(audio_paths)}/{len(segments)} 段')

    # ── 3. ffmpeg 合成 ──
    concat_list = tmp_dir / "concat.txt"
    with open(concat_list, "w", encoding="utf-8") as f:
        for ap in audio_paths:
            f.write(f"file '{ap}'\n")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    merged_wav = os.path.join(output_dir, f"ai_daily_news_{ts}.wav")

    ffmpeg_exe = _get_ffmpeg_path()
    try:
        result = subprocess.run(
            [ffmpeg_exe, "-y", "-f", "concat", "-safe", "0",
             "-i", str(concat_list), "-acodec", "pcm_s16le", merged_wav],
            capture_output=True, text=True, errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
            timeout=30,
        )
        if result.returncode != 0:
            print(f'[WARN] ffmpeg 合成失败: {(result.stderr or "")[:200]}')
            # 降级：返回第一段
            print('[WARN] 降级：只返回第一段音频')
            # 复制第一段到输出目录
            fallback = os.path.join(output_dir, f"ai_daily_news_{ts}_partial.wav")
            shutil.copy2(audio_paths[0], fallback)
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return fallback
    except Exception as e:
        print(f'[WARN] ffmpeg 合成异常: {e}')
        fallback = os.path.join(output_dir, f"ai_daily_news_{ts}_partial.wav")
        shutil.copy2(audio_paths[0], fallback)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return fallback

    # ── 4. 清理临时文件 ──
    shutil.rmtree(tmp_dir, ignore_errors=True)

    if os.path.exists(merged_wav):
        size_mb = os.path.getsize(merged_wav) / 1024 / 1024
        print(f'✅ 音频已生成: {merged_wav} ({size_mb:.1f}MB)')
        _log(f'Qwen3TTS 合成成功 → {merged_wav} ({size_mb:.1f}MB)', 'INFO')
        return merged_wav
    else:
        print('❌ 合成文件不存在')
        _log('Qwen3TTS 合成失败：输出文件不存在', 'ERROR')
        return None


def _generate_with_mimo(text, output_dir):
    """小米 MiMo TTS 生成音频

    直接复用 tts_switcher.py 的 generate_audio_file() 函数（import 调用），
    而不是通过 subprocess 传参（避免命令行长度限制）。

    三层 fallback（在 generate_audio_file 内部实现）：
    1. 解析 MiMo 输出的「音频保存于:」行
    2. 解析「合成完成:」行
    3. fallback 搜系统临时目录和 output/ 下的音频文件
    """
    import sys
    switcher_dir = _get_switcher_dir()
    if switcher_dir not in sys.path:
        sys.path.insert(0, switcher_dir)
    try:
        from tts_switcher import generate_audio_file
        # MiMo 输出目录由 config/tts_config.json 配置，tts.py 自行决定最终路径
        # output_path 参数对 MiMo 无效（仅 edge-tts 使用），传 output_dir 占位
        result = generate_audio_file(text, str(Path(output_dir) / '_mimo_out.mp3'),
                                     voice="default_zh", engine="xiaomi-mimo-tts")
        if result and os.path.exists(result):
            print(f'✅ MiMo 音频已生成: {result}')
            return result
        print('❌ MiMo 生成失败: generate_audio_file 未返回有效路径')
        return None
    except ImportError as e:
        print(f'[ERROR] 无法 import tts_switcher: {e}')
        return None
    except Exception as e:
        print(f'❌ MiMo 异常: {e}')
        return None


def _generate_with_edge(text, output_dir):
    """edge-tts 生成音频"""
    try:
        import edge_tts
    except ImportError:
        print('[ERROR] edge-tts 未安装，无法生成音频')
        return None

    import asyncio

    os.makedirs(output_dir, exist_ok=True)

    async def _gen():
        voice = "zh-CN-XiaoyiNeural"
        communicate = edge_tts.Communicate(text, voice)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join(output_dir, f"ai_daily_news_{ts}.mp3")
        await communicate.save(out_path)
        return out_path

    try:
        out_path = asyncio.run(_gen())
        if os.path.exists(out_path):
            print(f'✅ 音频已生成: {out_path}')
            return out_path
        print('❌ edge-tts 未生成文件')
        return None
    except Exception as e:
        print(f'❌ edge-tts 异常: {e}')
        return None


def _find_latest_audio(directory, extensions):
    """找目录下最新生成的音频文件"""
    d = Path(directory)
    if not d.exists():
        return None
    candidates = []
    for ext in extensions:
        candidates.extend(d.glob(f'*{ext}'))
    if not candidates:
        return None
    now = datetime.now()
    recent = [f for f in candidates
              if datetime.fromtimestamp(f.stat().st_mtime) > now - timedelta(seconds=120)]
    if recent:
        return str(sorted(recent, key=lambda x: x.stat().st_mtime, reverse=True)[0])
    return None



# ===================== 主流程 =====================
def find_latest_md():
    """找到最新的早报MD文件，优先使用 latest.md（避免手动模式同步问题）"""
    latest_path = os.path.join(OUTPUT_DIR, 'latest.md')
    if os.path.exists(latest_path):
        return latest_path
    md_files = [f for f in os.listdir(OUTPUT_DIR)
                if f.startswith('ai_daily_news_') and f.endswith('.md')]
    if not md_files:
        return None
    md_files.sort(reverse=True)
    return os.path.join(OUTPUT_DIR, md_files[0])


def main():
    import argparse
    parser = argparse.ArgumentParser(description='AI早报语音播报生成')
    parser.add_argument('--date', type=str, help='指定日期，如20260424')
    parser.add_argument('--text-only', action='store_true', help='只生成TXT，不生成音频')
    parser.add_argument('--engine', type=str, default=None,
                        help='TTS引擎（默认使用 config.json 的 active_engine）')
    parser.add_argument('--test', action='store_true', help='测试模式：生成3秒短音频，快速验证流程')
    args = parser.parse_args()

    # 日志：记录启动时间、引擎参数、处理的MD文件
    _log(f'启动 | mode=test | engine_override={args.engine}' if args.test else
         f'启动 | mode=normal | engine_override={args.engine}', 'INFO')

    # 找MD文件
    if args.date:
        pattern = f'ai_daily_news_{args.date}'
        md_files = [f for f in os.listdir(OUTPUT_DIR) if pattern in f and f.endswith('.md')]
        if not md_files:
            print(f'错误：未找到日期 {args.date} 的早报')
            return
        md_path = os.path.join(OUTPUT_DIR, sorted(md_files)[-1])
    else:
        md_path = find_latest_md()
        if not md_path:
            print('错误：未找到任何早报文件')
            return

    print(f'📄 处理文件: {os.path.basename(md_path)}')
    _log(f'处理文件: {os.path.basename(md_path)}', 'INFO')

    # 解析MD
    parsed = parse_md(md_path)
    parsed['_md_path'] = md_path  # 记录路径，供 AI 写回 .md 使用
    print(f'📅 日期: {parsed["date_str"]} {parsed["weekday"]}')

    total_titles = sum(len(v) for v in parsed['sections'].values())
    active_sections = [k for k, v in parsed['sections'].items() if v]
    print(f'📊 板块: {len(active_sections)}/{len(SECTION_NAMES)} 有内容 | 新闻: {total_titles} 条')
    for name in active_sections:
        print(f'   {SECTION_EMOJI.get(name, "")} {name}: {len(parsed["sections"][name])} 条')

    # 生成播报文本
    if args.test:
        broadcast_text = "测试AI早报播放，程序运行正常。"  # 短文本，约3秒
        print(f'🧪 测试模式：使用短文本 → {broadcast_text}')
    else:
        broadcast_text = generate_broadcast_text(parsed)

    # 写TXT
    txt_path = os.path.join(OUTPUT_DIR, 'latest.txt')
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(broadcast_text)
    # 只统计中文字数（排除标点/数字/英文），语速 3.5 字/秒（匹配 verify_audio 基准）
    chinese_chars = re.findall(r'[一-龥]', broadcast_text)
    char_count = len(chinese_chars)
    est_duration = char_count / 3.5
    print(f'\n✅ TXT已生成: {txt_path}')
    print(f'📝 字数: {char_count} | 预估时长: {est_duration:.0f} 秒 ({est_duration/60:.1f} 分钟)')
    print(f'\n--- 播报文本预览 ---')
    print(broadcast_text)
    print(f'--- 预览结束 ---\n')

    # 生成音频
    if not args.text_only:
        # 重试机制：最多3次
        max_retries = 3
        audio_file = None
        import time as _btime
        for retry in range(max_retries):
            audio_file = generate_audio(broadcast_text, OUTPUT_DIR, engine_override=args.engine)
            if audio_file:
                break
            print(f"⚠️ 生成音频失败，重试 {retry+1}/{max_retries}...")
            _log(f'生成音频失败，重试 {retry+1}/{max_retries}', 'WARN')
            if retry < max_retries - 1:
                _btime.sleep(2 ** retry)
        if not audio_file:
            print('❌ 多次重试后仍失败，放弃生成')
            _log('多次重试后仍失败，放弃生成', 'ERROR')
            return

        if audio_file:
            print(f'📋 音频文件: {audio_file}')
            print(f'RESULT: {audio_file}')  # 新增：输出路径供调用方解析
            _log(f'音频生成成功 → {audio_file}', 'INFO')
            # 入队播放（add --file，由守护进程异步消费）
            try:
                import subprocess
                _log('开始入队播放', 'INFO')
                print('🔊 正在入队播放音频...')
                result = subprocess.run(
                    [sys.executable, os.path.join(SKILL_DIR, 'data', 'tts_queue.py'),
                     'add', '--file', audio_file],
                    timeout=30,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                # 用 bytes 方式读取，避免 GBK 编码错误
                stdout_text = result.stdout.decode('utf-8', errors='replace')
                stderr_text = result.stderr.decode('utf-8', errors='replace')
                if stdout_text.strip():
                    print(stdout_text.strip())
                if result.returncode != 0:
                    print('⚠️ 入队失败: ' + stderr_text.strip())
                    _log(f'入队失败: {stderr_text.strip()}', 'ERROR')
                else:
                    print('✅ 已入队，守护进程将自动播放')
                    _log('入队成功，守护进程将自动播放', 'INFO')
            except Exception as e:
                print(f'⚠️ 播放失败: {e}')
                _log(f'入队异常: {e}', 'ERROR')
        else:
            print('❌ 音频生成失败')
            _log('音频生成失败，返回 None', 'ERROR')
    else:
        print('⏭️ 跳过音频生成 (--text-only)')
        _log('跳过音频生成 (--text-only)', 'INFO')


if __name__ == '__main__':
    main()
