# -*- coding: utf-8 -*-
"""
共享路径配置 — 消除硬编码路径

优先级：环境变量 > config/tts_config.json > data/tts_config_default.json > 兜底默认值

用法:
    from data._paths import (
        QUEUE_FILE, LOCK_FILE, PROCESSING_LOCK,
        QWEN_OUTPUT_DIR, EDGE_OUTPUT_DIR, MIMO_OUTPUT_DIR,
        VOICE_LIBRARY, SYSTEM_PYTHON, QWEN_PYTHON,
        STATE_FILE, TTS_URL,
        WORKBUDDY_PLAYING_FILE, WORKBUDDY_QUEUE_FILE,
    )
"""
import os
import sys
import json
from pathlib import Path

_SKILL_DIR = Path(__file__).parent.parent
_CONFIG_DIR = _SKILL_DIR / 'config'
_DATA_DIR = Path(__file__).parent
_OUTPUT_DIR = _SKILL_DIR / 'output'


def _load_cfg():
    """加载 TTS 配置：先读用户配置，不存在则用默认模板"""
    for p in [_CONFIG_DIR / 'tts_config.json', _DATA_DIR / 'tts_config_default.json']:
        if p.exists():
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
    return {}


def _first(*values):
    """返回第一个非空/非零值"""
    for v in values:
        if v:
            return v
    return None


_CFG = _load_cfg()
_ENGINES = _CFG.get('engines', {})
_PATHS_CFG = _CFG.get('paths', {})
_QUEUE_CFG = _CFG.get('queue', {})


def _env_or_cfg(env_key, cfg_keys, default):
    """env > cfg nested > default"""
    val = os.environ.get(env_key)
    if val:
        return val
    # 遍历嵌套 key 路径
    node = _CFG
    for k in cfg_keys:
        if isinstance(node, dict):
            node = node.get(k, {})
        else:
            node = {}
    if node and not isinstance(node, dict):
        return node
    return default


# === 队列文件 ===
_QUEUE_DIR = _first(
    _QUEUE_CFG.get('dir'),
    os.environ.get('TTS_QUEUE_DIR'),
)
if _QUEUE_DIR:
    _QUEUE_DIR = Path(_QUEUE_DIR)
else:
    _QUEUE_DIR = _OUTPUT_DIR / 'queue'

QUEUE_FILE = Path(
    _first(_QUEUE_CFG.get('queue_file'), os.environ.get('TTS_QUEUE_FILE'))
    or _QUEUE_DIR / 'ai_daily_queue.json'
)
LOCK_FILE = Path(
    _first(_QUEUE_CFG.get('lock_file'), os.environ.get('TTS_LOCK_FILE'))
    or _QUEUE_DIR / 'ai_daily_queue.lock'
)
PROCESSING_LOCK = Path(
    _first(_QUEUE_CFG.get('processing_lock'), os.environ.get('TTS_PROCESSING_LOCK'))
    or _QUEUE_DIR / 'ai_daily_processing.lock'
)

# === 音频输出目录 ===
_AUDIO_BASE = _first(
    _CFG.get('output_base_dir'),
    os.environ.get('TTS_OUTPUT_BASE_DIR'),
)
if _AUDIO_BASE:
    _AUDIO_BASE = Path(_AUDIO_BASE)
else:
    _AUDIO_BASE = _OUTPUT_DIR / 'audio'

_QWEN_CFG = _ENGINES.get('qwen3tts', {})
_EDGE_CFG = _ENGINES.get('edge-tts', {})
_MIMO_CFG = _ENGINES.get('xiaomi-mimo-tts', {})

QWEN_OUTPUT_DIR = Path(_first(_QWEN_CFG.get('output_dir')) or _AUDIO_BASE / 'qwen3tts')
EDGE_OUTPUT_DIR = Path(_first(_EDGE_CFG.get('output_dir')) or _AUDIO_BASE / 'edge-tts')
MIMO_OUTPUT_DIR = Path(_first(_MIMO_CFG.get('output_dir')) or _AUDIO_BASE / 'mimo')

# === 外部工具/资源（无兜底则留空，由调用方判断） ===
VOICE_LIBRARY = Path(
    _first(
        os.environ.get('TTS_VOICE_LIBRARY'),
        _CFG.get('voice_library_dir'),
    ) or ''
)
SYSTEM_PYTHON = Path(
    _first(
        os.environ.get('TTS_SYSTEM_PYTHON'),
        _CFG.get('system_python'),
    ) or sys.executable
)
QWEN_PYTHON = Path(
    _first(
        os.environ.get('TTS_QWEN_PYTHON'),
        _CFG.get('qwen_python'),
    ) or sys.executable
)

# === 音色轮换状态 ===
STATE_FILE = Path(
    _first(
        os.environ.get('TTS_VOICE_STATE_FILE'),
        _CFG.get('voice_state_file'),
    ) or _DATA_DIR / 'voice_rotation.json'
)

# === TTS 服务地址 ===
TTS_URL = _first(
    os.environ.get('TTS_SERVICE_URL'),
    _QWEN_CFG.get('service_url'),
) or 'http://localhost:7860'

# === 多源音频互斥（外部系统，播放前检测所有已启用的源） ===
_raw_sources = _CFG.get('audio_mutex_sources', [])
# 兼容旧版 workbuddy 单字段配置
if not _raw_sources:
    _wb_cfg = _CFG.get('workbuddy', {})
    if _wb_cfg:
        _wb_playing = _first(os.environ.get('TTS_WB_PLAYING_FILE'), _wb_cfg.get('playing_file'))
        _wb_queue = _first(os.environ.get('TTS_WB_QUEUE_FILE'), _wb_cfg.get('queue_file'))
        if _wb_playing or _wb_queue:
            _raw_sources = [{
                'name': 'WorkBuddy',
                'enabled': True,
                'playing_file': _wb_playing or '',
                'queue_file': _wb_queue or '',
            }]

AUDIO_MUTEX_SOURCES = []
for _src in _raw_sources:
    if not _src.get('enabled', False):
        continue
    playing = _src.get('playing_file', '')
    queue = _src.get('queue_file', '')
    if playing or queue:
        AUDIO_MUTEX_SOURCES.append({
            'name': _src.get('name', 'unknown'),
            'playing_file': Path(playing) if playing else None,
            'queue_file': Path(queue) if queue else None,
        })

# 保留旧名称向后兼容（实际上不再使用，但防止其他模块 import 报错）
WORKBUDDY_PLAYING_FILE = None
WORKBUDDY_QUEUE_FILE = None


# === 确保目录存在（按需创建） ===
def ensure_dirs():
    for d in [QUEUE_FILE.parent, QWEN_OUTPUT_DIR, EDGE_OUTPUT_DIR, MIMO_OUTPUT_DIR, STATE_FILE.parent]:
        d.mkdir(parents=True, exist_ok=True)
