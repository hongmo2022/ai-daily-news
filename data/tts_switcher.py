"""
TTS 统一切换器
根据 config.json 使用当前选定的引擎合成音频并播放

路径配置：所有路径从 config/tts_config.json 读取（via data/_paths.py）。
"""
import json
import os
import subprocess
import sys
import time
import tempfile
from datetime import datetime
from pathlib import Path

# 确保技能根目录在 sys.path 中（子进程调用时 data 包才能被导入）
_SKILL_ROOT = Path(__file__).parent.parent
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

SKILL_DIR = Path(__file__).parent
CONFIG_FILE = SKILL_DIR.parent / "config" / "tts_config.json"
QCLAW_SKILL = SKILL_DIR.parent / "qwen3-tts"

from data._paths import VOICE_LIBRARY, MIMO_OUTPUT_DIR

sys.path.insert(0, str(QCLAW_SKILL))


def load_config():
    if not CONFIG_FILE.exists():
        return None
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_audio(audio_bytes, output_dir):
    """保存音频到文件"""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = Path(output_dir) / f"tts_{ts}.wav"
    with open(out_path, "wb") as f:
        f.write(audio_bytes)
    return str(out_path)


def _ensure_dir(path):
    """确保目录存在"""
    Path(path).mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────
# Qwen3TTS 引擎
# ─────────────────────────────────────────────
def qwen3tts_speak(text, voice, output_dir=None):
    """使用 Qwen3TTS 合成并播放"""
    ref_audio_path = VOICE_LIBRARY / f"{voice}.wav"
    if not ref_audio_path.exists():
        print(f"FAIL: Voice file not found: {ref_audio_path}")
        return False

    try:
        sys.path.insert(0, str(QCLAW_SKILL))
        from index import generate
        result = generate(text=text, voice=voice, play=True)
        if output_dir and result and result.get("audio_bytes"):
            out = save_audio(result["audio_bytes"], output_dir)
            print(f"Saved: {out}")
        return True
    except Exception as e:
        print(f"FAIL: Qwen3TTS error: {e}")
        return False


# ─────────────────────────────────────────────
# Windows SAPI 引擎
# ─────────────────────────────────────────────
def _ps_escape(text):
    """安全转义文本用于 PowerShell 双引号字符串"""
    # 顺序重要：先转义反引号本身，再转义 $ 和 "
    return text.replace('`', '``').replace('$', '`$').replace('"', '`"')


def sapi_speak(text, voice_name, output_dir=None):
    """使用 Windows SAPI 合成并播放"""
    voice_map = {
        "Huihui": ("zh-CN", "Female"),
        "Zira": ("en-US", "Female"),
    }
    culture, gender = voice_map.get(voice_name, ("zh-CN", "Female"))

    # 确保目录存在
    if output_dir:
        _ensure_dir(output_dir)
        safe_out = output_dir.replace("\\", "\\\\")
    else:
        safe_out = ""

    safe_text = _ps_escape(text)

    script = SKILL_DIR / "_sapi_speak.ps1"
    script.write_text(
        f'''
Add-Type -AssemblyName System.Speech
$s = [System.Speech.Synthesis.SpeechSynthesizer]::new()
$targetCulture = [System.Globalization.CultureInfo]::new("{culture}")
$gender = [System.Speech.Synthesis.VoiceGender]::new("{gender}")
$age = [System.Speech.Synthesis.VoiceAge]::Adult

try {{
    $s.SelectVoiceByHints($gender, $age, 0, $targetCulture)
}} catch {{
    # fallback
}}

$outDir = "{safe_out}"
$ts = (Get-Date).ToString("yyyyMMdd_HHmmss")
$wavPath = "$outDir\\tts_$ts.wav"

$s.SetOutputToWaveFile($wavPath)
$s.Speak("{safe_text}")
$s.SetOutputToDefaultAudioDevice()

$player = [System.Media.SoundPlayer]::new($wavPath)
$player.PlaySync()

Write-Output "OK|$wavPath"
''',
        encoding="utf-8-sig"
    )

    try:
        result = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60
        )
        if result.returncode == 0 and (result.stdout or "").strip().startswith("OK"):
            out_path = result.stdout.strip().split("|")[1]
            print(f"OK: SAPI played with {voice_name}")
            print(f"Saved: {out_path}")
            return True
        else:
            print(f"FAIL: SAPI error: {result.stderr or result.stdout}")
            return False
    except subprocess.TimeoutExpired:
        print("FAIL: SAPI timeout")
        return False
    except Exception as e:
        print(f"FAIL: SAPI exception: {e}")
        return False


# ─────────────────────────────────────────────
# 小米 MiMo-TTS 引擎
# ─────────────────────────────────────────────
def get_night_volume():
    """
    判断当前是否为深夜时段，返回对应的音量。
    深夜时段：22:00~05:00（22, 23, 0, 1, 2, 3, 4, 5点）
    
    Returns:
        float: 音量（深夜返回 0.5，其他时段返回 1.0）
    """
    hour = datetime.now().hour
    if hour >= 22 or hour <= 5:
        return 0.5  # 深夜 50% 音量
    return 1.0  # 正常 100% 音量


def mimo_speak(text, voice="default_zh", output_dir=None, emotion=None):
    """使用小米 MiMo TTS 合成并播放"""
    MIMO_SKILL = SKILL_DIR.parent / "xiaomi-mimo-tts" / "scripts" / "tts.py"
    if not MIMO_SKILL.exists():
        print(f"FAIL: MiMo script not found: {MIMO_SKILL}")
        return False

    # 判断是否为深夜时段，自动降低音量
    volume = get_night_volume()
    
    cmd = [sys.executable, str(MIMO_SKILL), text, "--no-queue"]
    if volume < 1.0:
        cmd.extend(["--volume", str(volume)])
    if output_dir:
        cmd.extend(["--output", output_dir])
    if emotion:
        cmd.extend(["--emotion", emotion])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120
        )
        if result.returncode == 0:
            print(f"OK: MiMo TTS played (volume={volume})")
            return True
        else:
            print(f"FAIL: MiMo error: {result.stderr or result.stdout}")
            return False
    except subprocess.TimeoutExpired:
        print("FAIL: MiMo timeout")
        return False
    except Exception as e:
        print(f"FAIL: MiMo exception: {e}")
        return False


# ─────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────
def generate_audio_file(text, output_path, voice=None, engine=None):
    """只生成音频文件，不播放（用于早报等场景）
    
    Args:
        text: 要合成的文本
        output_path: 输出文件路径（仅用于 edge-tts，其他引擎忽略）
        voice: 音色名称（默认使用引擎配置的音色）
        engine: TTS引擎（默认使用 config.json 的 active_engine）
    """
    cfg = load_config()
    if not cfg:
        print("FAIL: config.json not found")
        return False

    from datetime import datetime as _dt
    engine = engine or cfg["active_engine"]
    voice = voice or cfg["engines"][engine]["voice"]
    output_dir = Path(output_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"[{engine}] Generating audio file, output_dir={output_dir}")
    
    # 根据引擎类型生成
    if engine == "qwen3tts":
        ref_audio_path = VOICE_LIBRARY / f"{voice}.wav"
        if not ref_audio_path.exists():
            print(f"FAIL: Voice file not found: {ref_audio_path}")
            return False
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        try:
            sys.path.insert(0, str(QCLAW_SKILL))
            from index import generate
            result = generate(text=text, voice=voice, play=False)
            if result and result.get("audio_bytes"):
                # Qwen3TTS 输出到 config 的 output_dir
                wav_path = str(output_dir / f"tts_{ts}.wav")
                with open(wav_path, "wb") as f:
                    f.write(result["audio_bytes"])
                print(f"✅ Audio saved: {wav_path}")
                return wav_path
            return False
        except Exception as e:
            print(f"FAIL: Qwen3TTS error: {e}")
            return False
    
    elif engine.startswith("edge"):
        # edge-tts 直接生成 MP3
        import asyncio
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        edge_out = str(output_dir / f"tts_{ts}.mp3")
        async def _generate_edge():
            import edge_tts
            communicate = edge_tts.Communicate(text, voice)
            chunks = []
            async for chunk in communicate.stream():
                if chunk['type'] == 'audio':
                    chunks.append(chunk['data'])
            audio_data = b''.join(chunks)
            with open(edge_out, 'wb') as f:
                f.write(audio_data)
            print(f"✅ Audio saved: {edge_out}")
            return edge_out
        
        try:
            return asyncio.run(_generate_edge())
        except Exception as e:
            print(f"FAIL: edge-tts error: {e}")
            return False
    
    elif engine == "xiaomi-mimo-tts":
        MIMO_SKILL = SKILL_DIR.parent / "xiaomi-mimo-tts" / "scripts" / "tts.py"
        if not MIMO_SKILL.exists():
            print(f"FAIL: MiMo script not found: {MIMO_SKILL}")
            return False
        # MiMo 生成到系统 TEMP 目录，keep=True 时复制到 MIMO_OUTPUT_DIR
        # 输出到 stderr（GBK 编码），需要用 locale.getpreferredencoding() 解码
        cmd = [sys.executable, str(MIMO_SKILL), text, "--no-queue", "--no-play"]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=False, timeout=240
            )
            # MiMo 输出 GBK 编码到 stderr，强制用 GBK 解码
            stderr_text = result.stderr.decode('gbk', errors='replace') if result.stderr else ''
            stdout_text = result.stdout.decode('utf-8', errors='replace') if result.stdout else ''
            combined = stderr_text + '\n' + stdout_text
            
            if result.returncode == 0:
                import re
                # 优先用「音频保存于:」行（最终保存位置，文件不会被删除）
                final_path_match = re.search(r'音频保存于:\s*(.+)', combined)
                if final_path_match:
                    raw = final_path_match.group(1).strip()
                    mp3 = re.search(r'([A-Za-z]:[^\n\r]+?\.mp3)', raw)
                    if mp3:
                        final_file = mp3.group(1).strip()
                        if os.path.exists(final_file):
                            print(f"✅ Audio saved: {final_file}")
                            return final_file
                # 其次用「合成完成:」行（TEMP目录，可能已被移动）
                path_match = re.search(r'合成完成:\s*(.+)', combined)
                if path_match:
                    raw_path = path_match.group(1).strip()
                    mp3_match = re.search(r'([A-Za-z]:[^\n\r]+?\.mp3)', raw_path)
                    if mp3_match:
                        temp_file = mp3_match.group(1).strip()
                        if os.path.exists(temp_file):
                            print(f"✅ Audio saved: {temp_file}")
                            return temp_file
                # fallback：找 TEMP 目录最新的 mp3
                from datetime import datetime, timedelta
                temp_dir = Path(tempfile.gettempdir())
                mp3_files = list(temp_dir.glob("tmp*.mp3"))
                if mp3_files:
                    now = datetime.now()
                    recent = [f for f in mp3_files if datetime.fromtimestamp(f.stat().st_mtime) > now - timedelta(seconds=120)]
                    if recent:
                        generated_file = str(sorted(recent, key=lambda x: x.stat().st_mtime, reverse=True)[0])
                        print(f"✅ Audio saved: {generated_file}")
                        return generated_file
                # 最后 fallback：找 MiMo 输出目录最新 mp3
                if MIMO_OUTPUT_DIR.exists():
                    mimo_files = list(MIMO_OUTPUT_DIR.glob("*.mp3"))
                    if mimo_files:
                        newest = str(sorted(mimo_files, key=lambda x: x.stat().st_mtime, reverse=True)[0])
                        print(f"✅ Audio saved: {newest}")
                        return newest
                print(f"FAIL: Could not find generated file in MiMo output")
                print(f"stderr: {stderr_text[:200]}")
                return False
            print(f"FAIL: MiMo error: {stderr_text[:300]}")
            return False
        except subprocess.TimeoutExpired:
            print("FAIL: MiMo timeout (240s)")
            return False
        except Exception as e:
            print(f"FAIL: MiMo exception: {e}")
            return False
    
    elif engine == "sapi":
        # SAPI 输出 WAV
        wav_path = output_path.replace('.mp3', '.wav')
        voice_map = {"Huihui": ("zh-CN", "Female"), "Zira": ("en-US", "Female")}
        culture, gender = voice_map.get(voice, ("zh-CN", "Female"))
        safe_text = _ps_escape(text)
        safe_out = str(Path(wav_path).parent).replace("\\", "\\\\")
        
        script = SKILL_DIR / "_sapi_generate.ps1"
        script.write_text(
            f'''
Add-Type -AssemblyName System.Speech
$s = [System.Speech.Synthesis.SpeechSynthesizer]::new()
$targetCulture = [System.Globalization.CultureInfo]::new("{culture}")
$gender = [System.Speech.Synthesis.VoiceGender]::new("{gender}")
$age = [System.Speech.Synthesis.VoiceAge]::Adult
try {{ $s.SelectVoiceByHints($gender, $age, 0, $targetCulture) }} catch {{}}
$s.SetOutputToWaveFile("{wav_path}")
$s.Speak("{safe_text}")
Write-Output "OK|{wav_path}"
''',
            encoding="utf-8-sig"
        )
        try:
            result = subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60
            )
            if result.returncode == 0 and "OK" in result.stdout:
                print(f"✅ Audio saved: {wav_path}")
                return wav_path
            print(f"FAIL: SAPI error: {result.stderr or result.stdout}")
            return False
        except Exception as e:
            print(f"FAIL: SAPI exception: {e}")
            return False
    
    else:
        print(f"FAIL: Unknown engine: {engine}")
        return False


def speak(text, voice=None, output_dir=None, emotion=None):
    """统一合成接口 - 所有引擎走守护进程队列，统一加锁播放"""
    cfg = load_config()
    if not cfg:
        print("FAIL: config.json not found")
        return False

    engine = cfg["active_engine"]
    voice = voice or cfg["engines"][engine]["voice"]

    print(f"[{engine}] voice={voice} text={text[:30]}{'...' if len(text) > 30 else ''}")

    # 所有引擎统一走守护进程 enqueue
    daemon_script = SKILL_DIR.parent / "qwen3-tts" / "ts_daemon.py"
    if not daemon_script.exists():
        print(f"FAIL: ts_daemon.py not found: {daemon_script}")
        return False

    cmd = [sys.executable, str(daemon_script), "enqueue", text,
           "--voice", voice, "--engine", engine]
    if emotion:
        cmd.extend(["--emotion", emotion])

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=60
        )
        if result.returncode == 0:
            print(result.stdout.strip())
            return True
        else:
            err = result.stderr.strip() or result.stdout.strip()
            print(f"FAIL: enqueue failed: {err}")
            return False
    except subprocess.TimeoutExpired:
        print("FAIL: enqueue timeout")
        return False
    except Exception as e:
        print(f"FAIL: enqueue exception: {e}")
        return False


def test():
    """测试当前配置"""
    cfg = load_config()
    if not cfg:
        print("FAIL: config.json not found")
        return

    engine = cfg["active_engine"]
    voice = cfg["engines"][engine]["voice"]
    print(f"TEST: engine={engine}, voice={voice}")
    speak(f"This is a test. Engine={engine}, voice={voice}.")


def main():
    args = sys.argv[1:]

    if not args or args[0] == "test":
        test()
    elif args[0] == "speak":
        # 支持: speak <text> [--emotion <emotion>]
        text_parts = []
        emotion = None
        i = 1
        while i < len(args):
            if args[i] == "--emotion" and i + 1 < len(args):
                emotion = args[i + 1]
                i += 2
            else:
                text_parts.append(args[i])
                i += 1
        text = " ".join(text_parts) if text_parts else "Test speech"
        speak(text, emotion=emotion)
    elif args[0] == "speak-v2":
        text = args[1] if len(args) > 1 else "Test speech"
        voice = args[2] if len(args) > 2 else None
        output_dir = args[3] if len(args) > 3 else None
        speak(text, voice, output_dir)
    elif args[0] == "generate":
        # 生成音频文件（不播放）
        # 用法: generate <text> <output_path> [voice] [engine]
        if len(args) < 3:
            print("Usage: tts_switcher.py generate <text> <output_path> [voice] [engine]")
            return
        text = args[1]
        output_path = args[2]
        voice = args[3] if len(args) > 3 else None
        engine = args[4] if len(args) > 4 else None
        result = generate_audio_file(text, output_path, voice, engine)
        if result:
            print(f"RESULT:{result}")
    elif args[0] == "switch":
        target = args[1] if len(args) > 1 else None
        if target not in ("qwen3tts", "sapi", "edge-tts", "xiaomi-mimo-tts"):
            print("Usage: tts_switcher.py switch qwen3tts|sapi|edge-tts|xiaomi-mimo-tts")
            return
        cfg = load_config()
        if not cfg:
            print("FAIL: config.json not found")
            return
        cfg["active_engine"] = target
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        print(f"Switched to {target}")
    else:
        print("Usage:")
        print("  tts_switcher.py test                      Test current config")
        print("  tts_switcher.py speak <text>              Speak with current config")
        print("  tts_switcher.py generate <text> <output>  Generate audio file only")
        print("  tts_switcher.py switch <engine>           Switch engine")


if __name__ == "__main__":
    main()
