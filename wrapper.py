# -*- coding: utf-8 -*-
"""
AI早报 Wrapper v2.2 — 串接采集 + 生成最终 MD + 智能语音

流程：
  有免费 Key  → ai_daily_news.py → generate_final.py（自动生成看点）→ broadcast.py（全自动）
  无免费 Key  → ai_daily_news.py → generate_final.py（输出 HIGHLIGHTS_PROMPT）→ 等待 AI Agent 手动处理
"""
import os
import sys
import subprocess
import glob

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SKILL_DIR, 'output')
LATEST_MD = os.path.join(OUTPUT_DIR, 'latest.md')


def run_script(name, timeout=300):
    """运行脚本，日志输出到 stderr，返回 returncode"""
    script = os.path.join(SKILL_DIR, name)
    if not os.path.exists(script):
        print(f'[ERROR] 脚本不存在: {name}', file=sys.stderr)
        return -1

    cmd = [sys.executable, script]
    print(f'[RUN] {name}', file=sys.stderr)
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding='utf-8',
            errors='replace',
            timeout=timeout,
            cwd=SKILL_DIR,
        )
        # 转发子进程的 stdout（含 HIGHLIGHTS_PROMPT）
        if result.stdout:
            print(result.stdout)
        if result.returncode != 0:
            print(f'[WARN] {name} 返回码={result.returncode}', file=sys.stderr)
            if result.stderr:
                print(f'[WARN] {result.stderr[:300]}', file=sys.stderr)
        else:
            print(f'[OK] {name} 完成', file=sys.stderr)
        return result.returncode
    except subprocess.TimeoutExpired:
        print(f'[ERROR] {name} 超时', file=sys.stderr)
        return -1
    except Exception as e:
        print(f'[ERROR] {name} 异常: {e}', file=sys.stderr)
        return -1


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    if args.dry_run:
        for name in ['ai_daily_news.py', 'generate_final.py', 'broadcast.py']:
            path = os.path.join(SKILL_DIR, name)
            print(f'  {"OK" if os.path.exists(path) else "MISSING"} {name}', file=sys.stderr)
        return

    # 步骤1：采集新闻
    rc1 = run_script('ai_daily_news.py', timeout=300)
    if rc1 != 0:
        print(f'[WARN] ai_daily_news.py 返回码={rc1}，检查临时文件是否已生成', file=sys.stderr)
        temp_files = glob.glob(os.path.join(OUTPUT_DIR, 'temp', 'ai_daily_news_*.md'))
        if not temp_files:
            print('[FATAL] 采集失败且无临时文件，终止流程', file=sys.stderr)
            sys.exit(1)
        print(f'[WARN] 但临时文件已存在，继续执行', file=sys.stderr)

    # 步骤2：生成最终 MD（免费 Key 可用时自动生成看点，否则输出 HIGHLIGHTS_PROMPT）
    rc2 = run_script('generate_final.py', timeout=120)
    if rc2 != 0:
        print('[WARN] generate_final.py 返回非0', file=sys.stderr)

    # 检查是否已自动生成看点（无需 AI Agent 介入）
    auto_done = False
    if os.path.exists(LATEST_MD):
        with open(LATEST_MD, 'r', encoding='utf-8') as f:
            md = f.read()
        if '<!-- TODAY_HIGHLIGHTS -->' not in md:
            auto_done = True

    if auto_done:
        # 免费 Key 工作正常，直接进入语音播报
        print(f'\n[INFO] 今日看点已自动生成，直接进入语音播报', file=sys.stderr)
        rc3 = run_script('broadcast.py', timeout=300)
        if rc3 == 0:
            print(f'\n[OK] 全自动流程完成！', file=sys.stderr)
        else:
            print(f'\n[WARN] 语音播报异常（返回码={rc3}），但 MD 已生成', file=sys.stderr)
    else:
        # 免费 Key 不可用，等待 AI Agent 手动填看点
        print(f'\n[NEXT] 请根据上方 HIGHLIGHTS_PROMPT 生成今日看点，', file=sys.stderr)
        print(f'       然后用 Edit 替换 {LATEST_MD} 中的 <!-- TODAY_HIGHLIGHTS -->', file=sys.stderr)
        print(f'       最后运行 python broadcast.py 生成语音播报', file=sys.stderr)


if __name__ == '__main__':
    main()
