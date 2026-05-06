#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
speak.py - Qwen3TTS 快捷播报脚本
用法:
  python speak.py <文本> [音色名称]
  python speak.py --greeting [音色名称]

路径配置：所有路径从 config/tts_config.json 读取（via data/_paths.py），兜底使用技能目录下的相对路径。

更新记录：
  2026-03-31 - 修正音色库路径、API 参数、播放方式（Qwen3TTS 环境 pygame）
"""

import sys
import os
import json
import requests
import base64
import subprocess
import tempfile
import hashlib
import time
from pathlib import Path

# 确保技能根目录在 sys.path 中（子进程调用时 data 包才能被导入）
_SKILL_ROOT = Path(__file__).parent.parent
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

if sys.platform == 'win32':
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if sys.stderr is not None:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# 最大字数（超过会截断，约28秒）
MAX_CHARS_PER_CHUNK = 140

# ============================================================================
# 文本预处理（Qwen3TTS 专用）
# ============================================================================

# 中文数字映射
_DIGITS = '零一二三四五六七八九十'

def _num_to_chinese(n: int) -> str:
    """将 0-99 的整数转为中文读法"""
    if n < 0 or n > 99:
        return str(n)  # 超出范围保持原样
    if n <= 10:
        return _DIGITS[n]
    if n < 20:
        return '十' + (_DIGITS[n % 10] if n % 10 else '')
    tens, ones = divmod(n, 10)
    return _DIGITS[tens] + '十' + (_DIGITS[ones] if ones else '')

def preprocess_text_for_qwen3tts(text: str) -> str:
    """Qwen3TTS 文本预处理：修复数字被读成英文的问题

    处理规则：
    1. 序号 "1、" "2、" "3、" → "一、" "二、" "三、"
    2. 序号 "1." "2." "3." → "一、" "二、" "三、"
    3. 括号序号 "(1)" "(2)" → "（一）" "（二）"
    4. 纯数字 + 量词（如 "33种" "0.4G" "10K"）保持原样（读英文不影响理解）
    5. 百分比/版本号等保持原样
    """
    import re

    # 1. 中文顿号/逗号前的序号：1、2、3、... → 一、二、三、
    #    匹配行首或标点后的 "数字+"、" 模式
    def _replace_seq(match):
        num = int(match.group(1))
        if 1 <= num <= 99:
            return _num_to_chinese(num) + '、'
        return match.group(0)

    # 行首序号：^数字+
    text = re.sub(r'^(\d+)[、\s]', _replace_seq, text, flags=re.MULTILINE)
    # 句中序号（句号/感叹号/问号后换行或空格后的数字+顿号）
    text = re.sub(r'(?<=[。！？；：\n])\s*(\d+)[、\s]', _replace_seq, text)

    # 2. 括号序号：(1) (2) → （一） （二）
    def _replace_paren(match):
        num = int(match.group(1))
        if 1 <= num <= 99:
            return '（' + _num_to_chinese(num) + '）'
        return match.group(0)
    text = re.sub(r'\((\d+)\)', _replace_paren, text)

    # 3. 英文句点序号（行首）：1. 2. 3. → 一、 二、 三、
    text = re.sub(r'^(\d+)\.(?=\s)', _replace_seq, text, flags=re.MULTILINE)

    return text


# ============================================================================
# 文本拆分
# ============================================================================

def split_text(text: str, max_chars: int = MAX_CHARS_PER_CHUNK) -> list:
    """按标点符号拆分文本，每段不超过 max_chars 字"""
    if len(text) <= max_chars:
        return [text]
    
    chunks = []
    current = ""
    
    # 按标点分割
    import re
    parts = re.split(r'([。！？；])', text)
    
    for part in parts:
        if not part:
            continue
        if len(current) + len(part) <= max_chars:
            current += part
        else:
            if current:
                chunks.append(current)
            current = part
    
    if current:
        chunks.append(current)
    
    # 如果按标点拆分后仍有超长的，直接截断
    result = []
    for chunk in chunks:
        if len(chunk) > max_chars:
            result.append(chunk[:max_chars])
        else:
            result.append(chunk)
    
    return result

from data._paths import (
    TTS_URL, VOICE_LIBRARY, QWEN_OUTPUT_DIR as OUTPUT_DIR,
    STATE_FILE, SYSTEM_PYTHON, ensure_dirs,
)

ensure_dirs()

VOICES = [
    "梅艳芳", "罗永浩", "郭德纲", "吴孟达",
    "周星驰", "罗家英", "小魔"
]
DEFAULT_GREETING_VOICE = "郭德纲"

# ============================================================================
# 音色管理
# ============================================================================

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

# ============================================================================
# 播放（Qwen3TTS 环境 pygame）
# ============================================================================

def play_audio(audio_path: str):
    try:
        # 直接在当前进程播放，不创建子进程（避免 Windows 音频子系统冲突导致无声）
        import pygame
        pygame.mixer.init()
        try:
            pygame.mixer.music.load(audio_path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.1)
        finally:
            pygame.mixer.quit()
    except Exception as e:
        print(f"[WARN] 播放失败: {e}")

# ============================================================================
# 服务检测
# ============================================================================

def check_server():
    try:
        r = requests.get(TTS_URL, timeout=3)
        return r.status_code < 500
    except:
        return False

# ============================================================================
# 生成语音
# ============================================================================

def _generate_to_file(text: str, voice_name: str, instruct: str, output_path: str) -> bool:
    """生成语音并保存到文件（不播放），用于 ffmpeg 合成"""
    if not voice_name:
        voice_name = get_current_voice()
    # 文本预处理：修复数字读法
    text = preprocess_text_for_qwen3tts(text)
    print(f"[TTS] 音色: {voice_name}")
    print(f"[TTS] 文本: {text}")
    print(f"[TTS] 输出: {output_path}")

    if not check_server():
        print("[ERROR] Qwen3TTS 服务未运行")
        return False

    voice_file = find_voice_file(voice_name)
    if not voice_file:
        print(f"[ERROR] 找不到音色文件: {voice_name}")
        return False

    try:
        with open(voice_file, "rb") as vf:
            post_data = {
                "text": text,
                "mode": "voice_clone",
                "max_new_tokens": 4096,
            }
            if instruct:
                post_data["instruct"] = instruct
            resp = requests.post(
                f"{TTS_URL}/generate",
                data=post_data,
                files={"ref_audio": vf},
                timeout=120,
            )
        if resp.status_code != 200:
            print(f"[ERROR] API 返回 {resp.status_code}: {resp.text[:200]}")
            return False
        result = resp.json()
        if "audio_b64" not in result:
            print(f"[ERROR] 响应格式错误: {result}")
            return False
        audio_bytes = base64.b64decode(result["audio_b64"])
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(audio_bytes)
        print(f"[TTS] 已保存: {output_path} ({len(audio_bytes)} bytes)")
        return True
    except Exception as e:
        print(f"[ERROR] {e}")
        return False


def generate_and_play(text: str, voice_name: str = None, auto_split: bool = True) -> bool:
    """生成语音并播放，支持自动拆分长文本"""
    if not voice_name:
        voice_name = get_current_voice()

    # 文本预处理：修复数字读法
    text = preprocess_text_for_qwen3tts(text)
    print(f"[TTS] 音色: {voice_name}")
    print(f"[TTS] 文本: {text}")

    # 检查并拆分文本
    chunks = split_text(text, MAX_CHARS_PER_CHUNK)
    if len(chunks) > 1:
        print(f"[TTS] 文本较长（{len(text)}字），已拆分为 {len(chunks)} 段")
    
    if not check_server():
        print("[ERROR] Qwen3TTS 服务未运行，请先启动服务")
        return False

    voice_file = find_voice_file(voice_name)
    if not voice_file:
        print(f"[ERROR] 找不到音色文件: {voice_name}")
        return False

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # 生成并保存所有分段
    audio_paths = []
    for i, chunk in enumerate(chunks):
        print(f"[TTS] 生成第 {i+1}/{len(chunks)} 段 ({len(chunk)}字)")
        
        output_name = hashlib.md5(f"{voice_name}_{chunk}_{i}".encode()).hexdigest()[:8]
        output_path = OUTPUT_DIR / f"{output_name}.wav"
        
        try:
            with open(voice_file, "rb") as vf:
                resp = requests.post(
                    f"{TTS_URL}/generate",
                    data={
                        "text": chunk, 
                        "mode": "voice_clone",
                        "max_new_tokens": 4096,
                    },
                    files={"ref_audio": vf},
                    timeout=120,
                )

            if resp.status_code != 200:
                print(f"[ERROR] API 返回 {resp.status_code}: {resp.text[:200]}")
                return False

            result = resp.json()
            if "audio_b64" not in result:
                print(f"[ERROR] 响应格式错误: {result}")
                return False

            audio_bytes = base64.b64decode(result["audio_b64"])
            with open(output_path, "wb") as f:
                f.write(audio_bytes)
            
            audio_paths.append(str(output_path))
            
        except Exception as e:
            print(f"[ERROR] {e}")
            return False

    # 依次播放所有分段
    for i, path in enumerate(audio_paths):
        print(f"[TTS] 播放第 {i+1}/{len(audio_paths)} 段")
        play_audio(path)
    
    print(f"[TTS] 全部播放完成，共 {len(audio_paths)} 段")
    return True


def generate_greeting(voice_name: str = None) -> bool:
    if not voice_name:
        voice_name = DEFAULT_GREETING_VOICE
    short_name = voice_name.split('-')[0] if '-' in voice_name else voice_name
    text = f"大哥我是{short_name}，今天是小弟为您服务。"
    return generate_and_play(text, voice_name)

# ============================================================================
# 主程序
# ============================================================================

def speak_with_queue(text: str, voice_name: str = None, engine: str = None, instruct: str = "") -> bool:
    """使用队列系统播放语音（异步模式，不等待）

    2026-04-19 重构：
    - 改用 subprocess.Popen，不等待子进程退出
    - speak.py 只负责"生成音频+加入队列"，不负责消费
    - 队列消费由独立的 ts_daemon.py 守护进程负责
    - 彻底解决 OpenClaw exec 超时导致锁残留的问题
    """
    import subprocess
    queue_script = Path(__file__).parent / "tts_queue.py"
    cmd = [str(SYSTEM_PYTHON), str(queue_script), "add", text]
    if voice_name and not voice_name.startswith("--"):
        cmd.append(voice_name)
    if engine:
        cmd.extend(["--engine", engine])
    if instruct:
        cmd.extend(["--instruct", instruct])

    # 静默启动：用 STARTUPINFO + SW_HIDE 强制隐藏窗口
    startupinfo = None
    if sys.platform == 'win32':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE

    # subprocess.Popen：启动子进程后立即返回，不等待
    # 使用 pythonw.exe（无控制台窗口）+ CREATE_NO_WINDOW，彻底避免 cmd 窗口闪现
    # 注意：不再使用 DETACHED_PROCESS，它与 python.exe 组合会导致新控制台窗口闪现
    subprocess.Popen(
        cmd,
        cwd=str(Path(__file__).parent),
        creationflags=subprocess.CREATE_NO_WINDOW,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        startupinfo=startupinfo,
    )
    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法:")
        print("  python speak.py <文本> [音色名称]")
        print("  python speak.py --greeting [音色名称]")
        print(f"可用音色: {', '.join(VOICES)}")
        print(f"当前音色: {get_current_voice()}")
        sys.exit(1)

    if sys.argv[1] == "--greeting":
        voice = sys.argv[2] if len(sys.argv) > 2 else None
        generate_greeting(voice)
    else:
        # 解析参数（支持 --engine / --instruct / --output 在任意位置）
        text = None
        voice = None
        engine = None
        instruct = None
        output_path = None
        i = 1
        while i < len(sys.argv):
            arg = sys.argv[i]
            if arg == "--engine" and i + 1 < len(sys.argv):
                engine = sys.argv[i + 1]
                i += 2
                continue
            elif arg.startswith("--engine="):
                engine = arg.split("=", 1)[1]
                i += 1
                continue
            elif arg == "--instruct" and i + 1 < len(sys.argv):
                instruct = sys.argv[i + 1]
                i += 2
                continue
            elif arg.startswith("--instruct="):
                instruct = arg.split("=", 1)[1]
                i += 1
                continue
            elif arg == "--output" and i + 1 < len(sys.argv):
                output_path = sys.argv[i + 1]
                i += 2
                continue
            elif arg.startswith("--output="):
                output_path = arg.split("=", 1)[1]
                i += 1
                continue
            elif text is None:
                text = arg
            elif voice is None:
                voice = arg
            i += 1

        if not text:
            print("[ERROR] 缺少文本参数")
            sys.exit(1)
        # 如果指定了 --output，直接生成音频文件（不走队列）
        if output_path:
            success = _generate_to_file(text, voice, instruct or "", output_path)
            sys.exit(0 if success else 1)
        # 使用队列系统，确保不打断
        speak_with_queue(text, voice, engine=engine, instruct=instruct or "")
