#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tts_queue.py - TTS 语音队列管理器
确保语音顺序播放，不打断上一句
支持与 WorkBuddy TTS 的音频互斥检测

用法:
  python tts_queue.py speak "<文本>" [音色名称]  # 添加语音到队列
  python tts_queue.py status                      # 查看队列状态
  python tts_queue.py clear                       # 清空队列

路径配置：所有路径从 config/tts_config.json 读取，兜底使用技能目录下的相对路径。
外部工具路径（音色库、Qwen3TTS Python 等）需在 config/tts_config.json 中配置。
"""

import sys
import os
import json
import time
import subprocess
import tempfile
import hashlib
import re
import atexit
from pathlib import Path
from typing import Optional, Dict

# 确保技能根目录在 sys.path 中（子进程调用时 data 包才能被导入）
_SKILL_ROOT = Path(__file__).parent.parent
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

if sys.platform == 'win32':
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# 路径配置（统一从 _paths 模块读取，消除硬编码）
from data._paths import (
    QUEUE_FILE, LOCK_FILE, PROCESSING_LOCK,
    QWEN_OUTPUT_DIR, EDGE_OUTPUT_DIR, MIMO_OUTPUT_DIR,
    VOICE_LIBRARY, SYSTEM_PYTHON, QWEN_PYTHON,
    STATE_FILE, TTS_URL,
    AUDIO_MUTEX_SOURCES,
    ensure_dirs,
)

# 向后兼容别名
OUTPUT_DIR = QWEN_OUTPUT_DIR

MAX_COMPLETED_ITEMS = 10  # 队列中最多保留的已完成记录数

AUDIO_CHECK_INTERVAL = 0.3    # 轮询间隔（秒）
MAX_WAIT_SECONDS = 30         # 最大等待时间（秒），智能等待后缩短

# 音频时长获取
try:
    from mutagen import File as MutagenFile
    _HAS_MUTAGEN = True
except ImportError:
    _HAS_MUTAGEN = False

# 音频检测关键词（来自 WorkBuddy 文档）
AUDIO_KEYWORDS = [
    "pygame", "tts_speak", "tts-speak", "edge_tts",
    "openclaw", "qclaw", "audio", "sound", "speaker",
    "mixer", "play", "voice", "speech"
]

VOICES = [
    "梅艳芳", "罗永浩", "郭德纲", "吴孟达",
    "周星驰", "罗家英", "小魔"
]

# 启动时确保必要目录存在
ensure_dirs()


class FileLock:
    """Windows 兼容的文件锁"""
    def __init__(self, lock_file):
        self.lock_file = lock_file

    def acquire(self):
        start = time.time()
        while True:
            if not self.lock_file.exists():
                break
            try:
                with open(self.lock_file, 'r', encoding='utf-8') as f:
                    lock_time = float(f.read().strip() or 0)
                if time.time() - lock_time > 30:
                    try:
                        self.lock_file.unlink()
                    except:
                        pass
                    break
            except:
                try:
                    self.lock_file.unlink()
                except:
                    pass
                break
            if time.time() - start > 5:
                try:
                    self.lock_file.unlink()
                except:
                    pass
                break
            time.sleep(0.05)
        
        with open(self.lock_file, 'w', encoding='utf-8') as f:
            f.write(str(time.time()))
    
    def release(self):
        try:
            if self.lock_file.exists():
                self.lock_file.unlink()
        except:
            pass
    
    def __enter__(self):
        self.acquire()
        return self
    
    def __exit__(self, *args):
        self.release()


# =============================================================================
# PID 存活检测 + 残留锁清理
# =============================================================================

def _is_pid_alive(pid: int) -> bool:
    """检查 PID 对应的进程是否还在运行"""
    try:
        import psutil
        return psutil.pid_exists(pid) and psutil.Process(pid).is_running()
    except ImportError:
        # 没有 psutil，用系统命令检查（静默启动，不闪窗口）
        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=3,
                startupinfo=si,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            return str(pid) in result.stdout
        except Exception:
            return False
    except Exception:
        return False


def cleanup_stale_lock():
    """检查 processing lock，如果持有者已死则自动清锁"""
    if not PROCESSING_LOCK.exists():
        return False
    try:
        pid_str = PROCESSING_LOCK.read_text().strip()
        old_pid = int(pid_str)
        if _is_pid_alive(old_pid):
            return False  # 进程还活着，不清理
        # 进程已死，清锁
        PROCESSING_LOCK.unlink()
        print(f"[队列] ⚠️ 清理残留锁（PID {old_pid} 已终止）")
        # 同时重置队列中的 playing 状态
        with FileLock(LOCK_FILE):
            queue = load_queue()
            if queue.get("playing"):
                queue["playing"] = False
                queue["current"] = None
                # 把 playing 状态的条目重置为 pending
                for item in queue["items"]:
                    if item["status"] == "playing":
                        item["status"] = "pending"
                save_queue(queue)
                print(f"[队列] 重置 {sum(1 for i in queue['items'] if i['status'] == 'pending')} 条排队项")
        return True
    except (ValueError, OSError):
        # 锁文件损坏，直接删除
        try:
            PROCESSING_LOCK.unlink()
        except Exception:
            pass
        return True


# atexit 注册：进程正常退出时清锁
def _exit_handler():
    try:
        if PROCESSING_LOCK.exists():
            pid_str = PROCESSING_LOCK.read_text().strip()
            if pid_str == str(os.getpid()):
                PROCESSING_LOCK.unlink()
    except Exception:
        pass


atexit.register(_exit_handler)


# =============================================================================
# WorkBuddy 音频互斥检测
# =============================================================================

def _get_audio_processes() -> list:
    """
    检测可能占用音频的进程
    参考 WorkBuddy 的实现方式
    """
    processes = []
    
    try:
        # 静默启动：隐藏 WMIC 窗口
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        
        # 使用 WMIC 获取 Python 进程列表
        result = subprocess.run(
            ["wmic", "process", "where", "name='python.exe'", "get", "ProcessId,CommandLine"],
            capture_output=True,
            text=True,
            timeout=5,
            startupinfo=startupinfo,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        
        if result.returncode == 0:
            for line in result.stdout.strip().split('\n'):
                if not line.strip() or 'CommandLine' in line:
                    continue
                # 检查命令行是否包含音频关键词
                line_lower = line.lower()
                for keyword in AUDIO_KEYWORDS:
                    if keyword.lower() in line_lower:
                        # 提取 PID
                        parts = line.strip().split()
                        if parts:
                            try:
                                pid = int(parts[-1].strip())
                                processes.append({
                                    "pid": pid,
                                    "keyword": keyword,
                                    "line": line.strip()[:100]
                                })
                            except:
                                pass
                        break
    except Exception as e:
        print(f"[WARN] 检测音频进程失败: {e}")
    
    return processes


def _get_audio_duration(path: str) -> Optional[float]:
    """获取音频文件时长（秒）。多策略尝试：wave → mutagen → pygame"""
    p = str(path)
    if not p:
        return None
    
    # 策略1：WAV 文件用标准库 wave
    if p.lower().endswith('.wav'):
        try:
            import wave as _wave
            with _wave.open(p, 'rb') as wf:
                return wf.getnframes() / wf.getframerate()
        except Exception:
            pass
    
    # 策略2：mutagen
    if _HAS_MUTAGEN:
        try:
            mf = MutagenFile(p)
            if mf is not None and hasattr(mf, 'info') and mf.info.length > 0:
                return mf.info.length
        except Exception:
            pass
    
    # 策略3：pygame.mixer.Sound
    try:
        import pygame as _pg
        if not _pg.mixer.get_init():
            _pg.mixer.init(frequency=24000, size=-16, channels=2, buffer=512)
            try:
                sound = _pg.mixer.Sound(p)
                dur = sound.get_length()
                return dur if dur > 0 else None
            finally:
                _pg.mixer.quit()
    except Exception:
        pass
    
    return None


def _check_mutex_source(source: dict) -> Optional[Dict]:
    """
    检测单个音频互斥源是否正在播放。

    Returns:
        None  - 未在播放
        dict  - 正在播放，含 name / expected_end / source
    """
    name = source['name']
    playing_file = source['playing_file']
    queue_file = source['queue_file']

    # 方法1：检查 playing 信号文件
    try:
        if playing_file and playing_file.exists():
            mtime = playing_file.stat().st_mtime
            if time.time() - mtime > 300:
                return None
            try:
                data = json.loads(playing_file.read_text())
                return {
                    "name": name,
                    "source": f"{name}.playing",
                    "expected_end": data.get("expected_end"),
                    "duration": data.get("duration"),
                    "since": data.get("since"),
                }
            except (json.JSONDecodeError, OSError):
                return {"name": name, "source": f"{name}.playing", "expected_end": None}
    except Exception:
        pass

    # 方法2：检查队列文件中 playing 状态的条目
    try:
        if queue_file and queue_file.exists():
            with open(queue_file, 'r', encoding='utf-8') as f:
                queue_data = json.load(f)
            for item in queue_data if isinstance(queue_data, list) else []:
                if item.get("status") == "playing":
                    expected_end = item.get("expected_end")
                    if expected_end is None and item.get("started_at") and item.get("duration"):
                        expected_end = item["started_at"] + item["duration"]
                    return {
                        "name": name,
                        "source": f"{name}.queue",
                        "expected_end": expected_end,
                    }
    except Exception:
        pass

    return None


def _is_any_audio_playing() -> Optional[Dict]:
    """
    检测所有已配置的音频互斥源。

    Returns:
        None  - 所有源均空闲
        dict  - 某个源正在播放
    """
    for source in AUDIO_MUTEX_SOURCES:
        result = _check_mutex_source(source)
        if result is not None:
            return result
    return None


# 保留旧名，向后兼容
def _is_workbuddy_playing():
    return _is_any_audio_playing()


def wait_for_audio_free(max_wait: float = None) -> bool:
    """
    轮询检测所有已配置的音频互斥源，等待任一播放完毕。

    返回值:
        True  - 音频已空闲，可以播放
        False - 等待超时，强制播放
    """
    if max_wait is None:
        max_wait = MAX_WAIT_SECONDS

    start_time = time.time()
    waited = False

    while True:
        elapsed = time.time() - start_time

        info = _is_any_audio_playing()

        if info is None:
            if elapsed > 1:
                print(f"[队列] ✓ 音频已空闲，继续播放")
            return True

        if elapsed >= max_wait:
            print(f"[队列] ⏰ 等待超时（{max_wait:.0f}秒），强制播放")
            return False

        # 计算预计剩余时间
        expected_end = info.get("expected_end")
        min_remaining = None
        if expected_end is not None:
            min_remaining = expected_end - time.time()
            if min_remaining < 0:
                min_remaining = None

        if not waited:
            source_name = info.get('name', '?')
            if min_remaining is not None:
                print(f"[队列] ⏳ {source_name} 正在播放，预计还需 {min_remaining:.1f}s，智能等待...")
            else:
                print(f"[队列] ⏳ {source_name} 正在播放，轮询等待...")
            waited = True

        # 智能等待
        if min_remaining is not None and min_remaining > 0.5:
            sleep_time = max(0.1, min_remaining - 0.3)
            print(f"[队列]   → sleep {sleep_time:.1f}s 到预计结束时刻")
            time.sleep(sleep_time)
        else:
            time.sleep(AUDIO_CHECK_INTERVAL)


# =============================================================================
# 音色管理
# =============================================================================

def get_current_voice():
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r', encoding='utf-8-sig') as f:
                return json.load(f).get("currentVoice", VOICES[0])
        except:
            pass
    return VOICES[0]


def rotate_voice():
    current = get_current_voice()
    try:
        idx = VOICES.index(current)
        next_voice = VOICES[(idx + 1) % len(VOICES)]
    except ValueError:
        next_voice = VOICES[0]
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump({"currentVoice": next_voice}, f)
    return next_voice


def find_voice_file(voice_name: str):
    """模糊匹配音色文件"""
    if not VOICE_LIBRARY.exists():
        return None
    exact = VOICE_LIBRARY / f"{voice_name}.wav"
    if exact.exists():
        return exact
    for f in VOICE_LIBRARY.glob("*.wav"):
        if voice_name in f.stem:
            return f
    return None


# =============================================================================
# 服务检测
# =============================================================================

def check_server():
    try:
        import requests
        r = requests.get(TTS_URL, timeout=3)
        return r.status_code < 500
    except:
        return False


# =============================================================================
# 生成语音
# =============================================================================

def generate_audio(text: str, voice_name: str, instruct: str = "") -> Path:
    if not check_server():
        print("[ERROR] Qwen3TTS 服务未运行")
        return None
    
    voice_file = find_voice_file(voice_name)
    if not voice_file:
        print(f"[ERROR] 找不到音色文件: {voice_name}")
        return None
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_name = hashlib.md5(f"{voice_name}_{text}_{instruct}".encode()).hexdigest()[:8]
    output_path = OUTPUT_DIR / f"{output_name}.wav"
    
    if output_path.exists() and output_path.stat().st_size > 1000:
        return output_path
    
    try:
        import requests
        import base64
        
        post_data = {"text": text, "mode": "voice_clone"}
        if instruct:
            post_data["instruct"] = instruct
        
        with open(voice_file, "rb") as vf:
            resp = requests.post(
                f"{TTS_URL}/generate",
                data=post_data,
                files={"ref_audio": vf},
                timeout=120,
            )
        
        if resp.status_code != 200:
            print(f"[ERROR] API 返回 {resp.status_code}")
            return None
        
        result = resp.json()
        if "audio_b64" not in result:
            print("[ERROR] 响应中无音频数据")
            return None
        
        audio_bytes = base64.b64decode(result["audio_b64"])
        with open(output_path, "wb") as f:
            f.write(audio_bytes)
        
        return output_path
    except Exception as e:
        print(f"[ERROR] 生成失败: {e}")
        return None


def generate_edge_audio(text: str, voice: str = "zh-CN-XiaoyiNeural") -> Path:
    """
    使用 edge-tts 生成语音（微软在线 TTS）
    参数:
        text  - 要说的文本
        voice - edge-tts 音色名，默认晓晓（中文女声）
    返回:
        生成的音频文件路径，或 None
    """
    import asyncio
    try:
        import edge_tts
    except ImportError:
        print("[ERROR] edge-tts 未安装，请运行: pip install edge-tts")
        return None

    EDGE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_name = hashlib.md5(f"edge_{text}".encode()).hexdigest()[:8]
    output_path = EDGE_OUTPUT_DIR / f"{output_name}.mp3"

    if output_path.exists() and output_path.stat().st_size > 1000:
        return output_path

    try:
        asyncio.run(_edge_speak_impl(text, voice, output_path))
        return output_path if output_path.exists() else None
    except Exception as e:
        print(f"[ERROR] edge-tts 生成失败: {e}")
        return None


def generate_mimo_audio(text: str, voice: str = "default_zh") -> Path:
    """
    使用 xiaomi-mimo-tts 生成语音
    参数:
        text  - 要说的文本
        voice - mimo 音色，默认 default_zh
    返回:
        生成的音频文件路径，或 None
    """
    import subprocess
    import sys

    MIMO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_name = hashlib.md5(f"mimo_{text}".encode()).hexdigest()[:8]
    output_path = MIMO_OUTPUT_DIR / f"{output_name}.mp3"
    
    if output_path.exists() and output_path.stat().st_size > 1000:
        return output_path
    
    try:
        # 直接导入 synthesize_speech，只合成不播放
        # 之前用 subprocess 调 tts.py --no-queue，但 --no-queue 只是跳过队列，
        # 仍然会直接 play_audio()，导致 ts_daemon.py 再播放一遍 = 播放两遍
        mimo_dir = Path(__file__).parent.parent / "xiaomi-mimo-tts" / "scripts"
        if mimo_dir not in [Path(p) for p in sys.path]:
            sys.path.insert(0, str(mimo_dir))
        from tts import synthesize_speech
        audio_path = synthesize_speech(
            text=text,
            voice=voice,
            audio_format="mp3",
            output=str(output_path),
        )
        if audio_path and Path(audio_path).exists():
            return Path(audio_path)
        return None
    except Exception as e:
        print(f"[ERROR] mimo-tts 生成失败: {e}")
        return None


async def _edge_speak_impl(text: str, voice: str, output_path: Path):
    """edge-tts 异步写入 MP3 文件"""
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(output_path))


# =============================================================================
# 音频检测（Windows 系统播放器）
# =============================================================================

def _get_audio_playing_processes():
    """通过 PowerShell 查询正在播放音频的进程"""
    ps_script = '''
Get-Process | Where-Object {$_.MainWindowTitle -ne ''} |
Where-Object {$_.ProcessName -match 'wmplayer|groove|music|vlc|mpv|audacity|Spotify|QQMusic'} |
Select-Object ProcessName, MainWindowTitle | ConvertTo-Json -Compress
'''
    try:
        # 静默启动：隐藏 PowerShell 窗口
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        result = subprocess.run(
            ['powershell', '-NoProfile', '-Command', ps_script],
            capture_output=True, text=True, timeout=5, encoding='utf-8', errors='replace',
            startupinfo=si,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        return result.stdout.strip() if result.stdout.strip() else None
    except:
        return None

def wait_for_windows_audio_free(max_wait=60.0, check_interval=0.5):
    """
    等待 Windows 系统音频设备空闲（系统播放器不写 playing.json）
    2026-04-15 修复：TTS 被系统播放器（os.startfile）打断的问题
    """
    start = time.time()
    last_msg = ''

    while True:
        playing = _get_audio_playing_processes()
        if not playing:
            elapsed = time.time() - start
            if elapsed > 1.5:
                print(f"[队列] 系统音频已空闲（等待了 {elapsed:.1f}秒）")
            return True

        elapsed = time.time() - start
        msg = f"[队列] 检测到播放器正在播放，等待中... ({elapsed:.0f}s/{max_wait}s)"
        if msg != last_msg:
            print(msg)
            last_msg = msg

        if elapsed >= max_wait:
            print(f"[队列] 等待超时（{max_wait}秒），强制播放")
            return False

        time.sleep(check_interval)


# =============================================================================
# 播放（pygame）
# =============================================================================

def play_audio(audio_path: Path):
    """
    播放音频文件。

    2026-04-13 方案：
    - PTY 会话 exec 超时导致子进程被 kill，音频没播完就凉了
    - 改用 os.startfile() → Windows 默认播放器播放
    - 2026-04-13 下午进一步修复：pygame 在当前进程播放，不走子进程

    2026-04-15 修复：
    - play_audio 前先等待 Windows 系统音频设备空闲
    - 解决 os.startfile 启动的播放器与 pygame 抢音频设备的问题
    """
    # 2026-04-15 新增：播放前检测系统音频设备
    wait_for_windows_audio_free(max_wait=60.0, check_interval=0.5)

    try:
        import pygame as _pg
        _pg.mixer.init(frequency=24000, size=-16, channels=2, buffer=512)
        _pg.mixer.music.load(str(audio_path))
        _pg.mixer.music.play()
        while _pg.mixer.music.get_busy():
            time.sleep(0.05)
        _pg.mixer.quit()
        return True
    except Exception as e:
        print(f"[ERROR] 播放失败: {e}")
        return False


# =============================================================================
# 队列管理
# =============================================================================

def load_queue():
    if QUEUE_FILE.exists():
        try:
            with open(QUEUE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {"items": [], "playing": False, "current": None}


def save_queue(queue):
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(QUEUE_FILE, 'w', encoding='utf-8') as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)


def trim_completed(queue):
    """清理过多的 completed 记录，只保留最近的 MAX_COMPLETED_ITEMS 条"""
    completed = [i for i in queue["items"] if i["status"] in ("completed", "failed")]
    if len(completed) <= MAX_COMPLETED_ITEMS:
        return queue
    # 按创建时间排序，保留最新的
    completed.sort(key=lambda x: x.get("created_at", 0))
    to_remove = set(id(i) for i in completed[:-MAX_COMPLETED_ITEMS])
    queue["items"] = [i for i in queue["items"] if id(i) not in to_remove]
    return queue


# ============================================================================
# 引擎管理（模块级）
# ============================================================================

def _get_active_engine():
    """读取 config/tts_config.json，返回当前激活的 TTS 引擎"""
    try:
        cfg_path = Path(__file__).parent.parent / "config" / "tts_config.json"
        # 如果用户配置文件不存在，尝试默认模板
        if not cfg_path.exists():
            cfg_path = Path(__file__).parent / "tts_config_default.json"
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("active_engine", "qwen3tts")
    except Exception:
        return "qwen3tts"


# ============================================================================
# 队列操作
# ============================================================================

def add_to_queue(text: str, voice_name: str = None, auto_consume: bool = True, engine: str = None, pre_audio_path: str = None, instruct: str = ""):
    """添加语音到队列，生成音频后可选触发播放

    2026-04-28 新增 pre_audio_path 参数：
    - 如果传入了已有音频文件路径，跳过 TTS 生成，直接用该文件入队
    - 用于 ai_daily_news 播报场景（音频已由 broadcast.py 生成好）

    2026-04-21 修复：engine 默认值改为动态读取 config.json
    engine=None 时自动读 tts-switcher/config.json 的 active_engine
    - "qwen3": Qwen3TTS（需7860端口服务）
    - "edge":  edge-tts（微软在线，需网络）
    - "xiaomi": xiaomi-mimo-tts（小米 MiMo，情感语音）

    2026-04-19 重构：
    - auto_consume=True（默认）：原有行为，锁不存在时自己消费
    - auto_consume=False：只入队，由 ts_daemon.py 守护进程消费
    """
    # 动态获取引擎（不在这里写默认值，防止闭包问题）
    if engine is None:
        engine = _get_active_engine()

    # 按引擎设置默认音色
    if engine.startswith("edge") and not voice_name:
        voice_name = "zh-CN-XiaoyiNeural"
    elif engine.startswith("xiaomi") or engine == "xiaomi-mimo-tts":
        if not voice_name:
            voice_name = "default_zh"
    elif engine == "qwen3tts" and not voice_name:
        voice_name = "小魔"
    elif not voice_name:
        voice_name = get_current_voice()

    # 关键改动：pre_audio_path 存在时跳过 TTS 生成（音频已由 broadcast.py 生成）
    if pre_audio_path:
        audio_path = Path(pre_audio_path)
        if not audio_path.exists():
            print(f"[ERROR] 指定音频文件不存在: {pre_audio_path}")
            return False
        print(f"[队列] 使用已有音频文件: {audio_path.name}")
    else:
        # 按引擎生成音频
        if engine.startswith("edge"):
            audio_path = generate_edge_audio(text, voice_name)
        elif engine.startswith("xiaomi") or engine == "xiaomi-mimo-tts":
            audio_path = generate_mimo_audio(text, voice_name)
        elif engine == "qwen3tts":
            audio_path = generate_audio(text, voice_name, instruct=instruct)
        else:
            # 默认走 edge-tts (兜底)，使用 edge 默认音色
            audio_path = generate_edge_audio(text, "zh-CN-XiaoyiNeural")

        if not audio_path:
            return False

    item = {
        "id": hashlib.md5(f"{time.time()}_{text}".encode()).hexdigest()[:8],
        "text": text,
        "voice": voice_name,
        "engine": engine,
        "audio_path": str(audio_path),
        "status": "pending",
        "created_at": time.time()
    }

    # 2026-04-15 修复：添加前先清理残留锁，防止锁残留导致队列卡死
    cleanup_stale_lock()

    with FileLock(LOCK_FILE):
        queue = load_queue()
        
        # ========== 新增：重复检测 ==========
        new_audio_path = str(audio_path)
        for existing_item in queue.get("items", []):
            # 检查状态是否为pending或playing，且音频路径相同
            if (existing_item.get("status") in ("pending", "playing") and 
                existing_item.get("audio_path") == new_audio_path):
                print(f"[队列] 跳过重复添加：{Path(new_audio_path).name} 已存在 {existing_item['status']} 状态的条目")
                return False
        # ========== 重复检测结束 ==========
        
        queue["items"].append(item)
        trim_completed(queue)
        # 改用锁文件真实状态判断，不依赖 queue["playing"] 字段
        lock_exists = PROCESSING_LOCK.exists()
        save_queue(queue)

    print(f"[队列] 已添加: {text[:30]}...")

    # 只有锁不存在时才触发处理（锁存在说明有进程正在处理）
    # auto_consume=False 时跳过后续逻辑，由 daemon 消费
    if auto_consume and not lock_exists:
        process_queue()

    return True




def process_queue():
    """处理队列 - 确保只有一个进程在处理，支持与 WorkBuddy 互斥"""
    
    # 自动清理残留锁（进程已死但锁文件还在的情况）
    cleanup_stale_lock()
    
    # 再次检查处理锁（正常情况下锁已被清理或不存在）
    if PROCESSING_LOCK.exists():
        print("[队列] 已有处理进程在运行，跳过")
        return
    
    # 写入处理锁
    with open(PROCESSING_LOCK, 'w', encoding='utf-8') as f:
        f.write(str(os.getpid()))
    
    try:
        while True:
            # 取下一条
            with FileLock(LOCK_FILE):
                queue = load_queue()
                next_item = None
                for item in queue["items"]:
                    if item["status"] == "pending":
                        next_item = item
                        break
                
                if not next_item:
                    queue["playing"] = False
                    queue["current"] = None
                    save_queue(queue)
                    return
                
                queue["playing"] = True
                queue["current"] = next_item["id"]
                next_item["status"] = "playing"
                # 写入音频时长和预计结束时间，供 WorkBuddy 智能等待
                now = time.time()
                next_item["started_at"] = now
                audio_dur = _get_audio_duration(next_item.get("audio_path", ""))
                if audio_dur:
                    next_item["duration"] = audio_dur
                    next_item["expected_end"] = now + audio_dur
                else:
                    next_item["duration"] = None
                    next_item["expected_end"] = None
                save_queue(queue)
            
            # ===== 关键改动：播放前等待 WorkBuddy 完成 =====
            print(f"[队列] 检测音频设备状态...")
            wait_for_audio_free()
            
            # 播放
            print(f"[播放] {next_item['voice']}: {next_item['text'][:40]}...")
            audio_path = Path(next_item["audio_path"])
            
            if audio_path.exists() and play_audio(audio_path):
                result = "completed"
            else:
                result = "failed"
            
            # 标记完成
            with FileLock(LOCK_FILE):
                queue = load_queue()
                for item in queue["items"]:
                    if item["id"] == next_item["id"]:
                        item["status"] = result
                        break
                save_queue(queue)
            
            print(f"[{'完成' if result=='completed' else '失败'}] {next_item['text'][:30]}...")
    
    finally:
        # 清理处理锁
        try:
            PROCESSING_LOCK.unlink()
        except:
            pass


def get_status():
    with FileLock(LOCK_FILE):
        queue = load_queue()
    
    pending = [i for i in queue["items"] if i["status"] == "pending"]
    playing = [i for i in queue["items"] if i["status"] == "playing"]
    completed = [i for i in queue["items"] if i["status"] == "completed"]
    
    print(f"状态: {'播放中' if queue.get('playing') else '空闲'}")
    print(f"待播放: {len(pending)} 条")
    print(f"播放中: {len(playing)} 条")
    print(f"已完成: {len(completed)} 条")
    
    # 显示音频互斥源状态
    info = _is_any_audio_playing()
    if info:
        remaining = ""
        exp_end = info.get("expected_end")
        if exp_end:
            r = exp_end - time.time()
            if r > 0:
                remaining = f"，预计还需 {r:.1f}s"
        print(f"⚠️ {info.get('name', '?')} 正在播放音频{remaining}，请等待")


def clear_queue():
    with FileLock(LOCK_FILE):
        queue = load_queue()
        queue["items"] = [i for i in queue["items"] if i["status"] == "completed"]
        queue["playing"] = False
        queue["current"] = None
        save_queue(queue)
    print("[队列] 已清空")


def main():
    if len(sys.argv) < 2:
        print("用法:")
        print("  python tts_queue.py speak \"<文本>\" [音色名称] [--engine qwen3tts|edge-tts|xiaomi-mimo-tts]")
        print("  python tts_queue.py add \"<文本>\" [音色名称] [--file <已有音频路径>]")
        print("  python tts_queue.py add --file=<已有音频路径>  # 文本可选")
        print("  python tts_queue.py status")
        print("  python tts_queue.py clear")
        print(f"可用音色: {', '.join(VOICES)}")
        print(f"当前音色: {get_current_voice()}")
        print("引擎: qwen3tts / edge-tts / xiaomi-mimo-tts（默认从 config.json 读取）")
        print("--file: 传入已有音频文件路径，跳过 TTS 生成，用于 ai-daily-news 播报场景")
        sys.exit(1)

    command = sys.argv[1]

    # 解析 --engine 参数（支持在任意位置）
    # 默认从 tts-switcher/config.json 读取 active_engine
    engine = _get_active_engine()
    # 正确过滤：去掉 --engine 和它的值
    argv = []
    skip_next = False
    for a in sys.argv[2:]:
        if skip_next:
            skip_next = False
            continue
        if a.startswith("--engine="):
            engine = a.split("=", 1)[1]
            continue
        elif a == "--engine":
            skip_next = True
            idx = list(sys.argv).index(a)
            if idx + 1 < len(sys.argv):
                engine = sys.argv[idx + 1]
            continue
        if a.startswith("--engine"):
            continue
        argv.append(a)

    # 解析 --instruct 参数（支持在任意位置）
    instruct = ""
    remaining_after_instruct = []
    skip_next = False
    for a in argv:
        if skip_next:
            skip_next = False
            continue
        if a.startswith("--instruct="):
            instruct = a.split("=", 1)[1]
        elif a == "--instruct":
            idx = argv.index(a)
            if idx + 1 < len(argv):
                instruct = argv[idx + 1]
                skip_next = True
        else:
            remaining_after_instruct.append(a)
    argv = remaining_after_instruct

    if command == "add":
        # 2026-04-19：只入队，不消费（由 ts_daemon.py 负责播放）
        # 2026-04-28：新增 --file 参数，支持传入已有音频文件（跳过 TTS 生成）
        # 先解析 --file 参数（支持 --file <path> 或 --file=<path>）
        pre_audio = None
        remaining_argv = []
        skip_next = False
        for a in argv:
            if skip_next:
                skip_next = False
                continue
            if a.startswith("--file="):
                pre_audio = a.split("=", 1)[1]
            elif a == "--file":
                idx = argv.index(a)
                if idx + 1 < len(argv):
                    pre_audio = argv[idx + 1]
                    skip_next = True
            else:
                remaining_argv.append(a)
        argv = remaining_argv
        # --file 模式下文本可选，无文件时必须提供文本
        if not pre_audio and len(argv) < 1:
            print("[ERROR] 缺少文本参数（或使用 --file 指定已有音频文件）")
            sys.exit(1)
        text = argv[0] if len(argv) > 0 else ""
        voice = argv[1] if len(argv) > 1 else None
        add_to_queue(text, voice, auto_consume=False, engine=engine, pre_audio_path=pre_audio, instruct=instruct)
        # 顺便打印队列状态
        get_status()

    elif command == "speak":
        # 原有行为：入队后立即消费（兼容旧调用方式）
        if len(argv) < 1:
            print("[ERROR] 缺少文本参数")
            sys.exit(1)
        text = argv[0]
        voice = argv[1] if len(argv) > 1 else None
        add_to_queue(text, voice, auto_consume=True, engine=engine, instruct=instruct)

    elif command == "status":
        get_status()

    elif command == "clear":
        clear_queue()

    else:
        print(f"[ERROR] 未知命令: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
