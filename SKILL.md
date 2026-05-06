# AI 早报技能 (ai-daily-news)

> 📦 v2.2 — 免费 API 自动生成今日看点 + 多源音频互斥 + 全自动无人值守


> 🤖 每日 AI 科技新闻聚合、分类与语音播报

## 功能概述

每天 09:30 自动采集过去 24 小时的 AI 科技新闻，按六大分类整理成精美的 Markdown 早报，并支持语音播报生成。

### ✨ v2.2 新特性：免费 API 自动生成今日看点

无需 AI Agent 介入，可配置免费大模型 API 自动生成「今日看点」总结：

| 厂商 | 模型 | 费用 | 注册地址 |
|------|------|------|----------|
| 智谱 | GLM-4.7-Flash | **免费模型** | open.bigmodel.cn |

配置详见 `config/free_api.env.example`。至少配一个即可启用全自动模式。

## 手动触发

当用户在对话中要求"跑一下AI早报"、"手动执行早报"、"现在出早报"等时：

```powershell
python wrapper.py
```

wrapper.py 根据是否配置了免费 API Key 自动选择路径：

**路径 A：已配置免费 Key（全自动）**
```
ai_daily_news.py → generate_final.py（自动生成看点）→ broadcast.py（语音播报）
→ 全程无需 AI Agent 介入，完成后告知用户"全自动流程完成"
```

**路径 B：未配置免费 Key（需 AI Agent 参与）**
```
ai_daily_news.py → generate_final.py（输出 HIGHLIGHTS_PROMPT）
→ AI Agent 根据 prompt 生成今日看点 → 替换 <!-- TODAY_HIGHLIGHTS -->
→ 运行 broadcast.py 生成语音播报
```

**简短版（仅语音播报）**：
```powershell
python broadcast.py
```

> ⚠️ AI Agent 模式下，不要主动贴出 latest.md 全文（消耗 3000-4000 token）。用户要求时才贴，并提醒消耗。
> ⚠️ 在 PowerShell 中串联命令请使用 `; if ($?) { }` 而非 `&&`

## 核心特性

- **多源聚合**：机器之心 API + 量子位 RSS + 36氪 + 雷峰网 + 虎嗅(镜像RSS) + 新智元(爬虫) + The Verge + TechCrunch
- **六大分类**：模型发布 / 产品应用 / 开发生态 / 资本动态 / 政策法规 / 前瞻传闻
- **智能分类**：基于关键词匹配的自动分类 + 重要性标注
- **广告过滤**：多维度综合评分（品牌主语检测 + 产品发布模式 + 合作推广模式 + 来源可信度 + 财报模式），采集阶段直接过滤
- **设计增强**：emoji 标签 + 星级重点 + 摘要预览
- **全中文**：国际新闻自动过滤 + 中文优先

## 六大分类说明

| #   | 分类   | emoji | 权威性      |
| --- | ---- | ----- | -------- |
| 1   | 模型发布 | 🤖    | ⭐⭐⭐⭐⭐    |
| 2   | 产品应用 | 🚀    | ⭐⭐⭐⭐     |
| 3   | 开发生态 | 🛠️   | ⭐⭐⭐⭐     |
| 4   | 资本动态 | 💰    | ⭐⭐⭐⭐     |
| 5   | 政策法规 | ⚖️    | ⭐⭐⭐⭐⭐    |
| 6   | 前瞻传闻 | 🔮    | ⭐⭐⭐（可略低） |

## 时间窗口

- **数据范围**：昨天 09:31 ~ 今天 09:30（北京时区）
- **生成时间**：每天 09:30（cron 定时）
- **新闻条数**：目标 10-20 条（按内容质量动态分配）

## 文件结构

```

├── ai_daily_news.py    # 主脚本：新闻采集 + 广告过滤 + MD 生成
├── generate_final.py   # 第二步：读干净md + 查时段/节日 → 免费API生成看点 或 输出HIGHLIGHTS_PROMPT
├── free_providers.py   # 免费厂商自动切换模块（智谱，无需用户操作）
├── wrapper.py          # 一键入口：串接采集 → 生成 → 语音（免费Key可用时全自动）
├── broadcast.py        # 语音播报：MD → TXT → MP3/WAV
├── news_sources.py     # 数据源采集模块（8个来源）
├── config/
│   ├── ad_filter.json        # 广告词过滤表
│   ├── polyphone_map.json    # 多音字映射表（仅播报用）
│   ├── tts_config.json       # TTS 引擎 + 音频互斥源配置
│   ├── tts_duration_limits.json  # TTS 时长限制规则
│   └── free_api.env.example  # 免费 API Key 配置模板
├── SKILL.md            # 本文档
├── output/             # 生成的早报
│   ├── ai_daily_news_YYYYMMDD_HHMM.md  # 每日 MD 原稿
│   ├── latest.md       # 最新 MD
│   ├── latest.txt      # 播报纯文本
│   ├── free_provider_status.json  # 免费厂商失效状态
│   └── <TTS引擎生成的音频文件>
└── data/               # TTS 依赖脚本 + 缓存数据
    ├── tts_queue.py          # TTS 队列管理器（音频排队播放，不阻塞主进程）
    ├── speak.py              # Qwen3TTS 调用入口（文字→音频，支持 --output 只生成不播放）
    ├── tts_switcher.py       # 统一 TTS 切换器（路由到当前激活引擎）
    ├── tts_config_default.json  # TTS 配置默认模板（用户可在 config/tts_config.json 覆盖）
    └── holiday_cache.json    # 节日缓存数据
```

## 手动运行

### 全自动流程（推荐 — 需配置免费 Key）

配置任一免费 API Key 后，一键完成采集→看点→播报：

```bash
python wrapper.py
# → 自动检测到免费 Key 可用 → 生成完整 MD → 自动跑 broadcast.py
# → 全程无人值守
```

> 💡 免费 Key 配置方法见 `config/free_api.env.example`

### 手动流程（未配置免费 Key）

```bash
# 步骤1：采集 + 生成 MD + 输出 HIGHLIGHTS_PROMPT
python wrapper.py
# → 输出 HIGHLIGHTS_PROMPT，AI Agent 根据 prompt 生成今日看点
# → AI Agent 用 Edit 替换 output/latest.md 中的 <!-- TODAY_HIGHLIGHTS -->

# 步骤2：语音播报
python broadcast.py
# → 守护进程自动播放，无需额外操作
```

> ⚠️ **关键规则**：步骤1失败时不要继续执行步骤2，避免用旧文件凑合播报。

### 独立运行

```bash
# 只生成文本早报（不触发语音播报）
python ai_daily_news.py --text-only

# 独立运行语音播报（不重新采集，读 latest.md）
python broadcast.py

# 只生成 TXT（不生成音频）
python broadcast.py --text-only

# 指定日期
python broadcast.py --date 20260424

# 指定 TTS 引擎（覆盖 config.json）
python broadcast.py --engine xiaomi-mimo-tts

# 仅测试数据采集
python news_sources.py
```

> ⚠️ `broadcast.py` 自己读 `config/tts_config.json` 决定引擎（`auto` 模式自动探测），不依赖外部传参。`--engine` 仅用于手动覆盖。

## 数据源

### 🇨🇳 国内源

| 优先级 | 数据源  | 类型   | 状态   | 广告比例               |
| --- | ---- | ---- | ---- | ------------------ |
| 1   | 机器之心 | API  | ✅ 可用 | ~20%（产品发布软文）       |
| 2   | 量子位  | 网页爬虫 | ✅ 可用 | 低                  |
| 3   | 36氪  | RSS  | ✅ 可用 | ~50%（含自家推广 + 非 AI） |
| 4   | 雷峰网  | RSS  | ✅ 可用 | ~40%（车企软文重灾区）      |
| 5   | 虎嗅   | RSS  | ✅ 可用 | ~90%（几乎全非 AI）      |

### 🌍 国际源

| 优先级 | 数据源            | 类型   | 状态   |
| --- | -------------- | ---- | ---- |
| 1   | Anthropic Blog | 网页爬虫 | ✅ 可用 |
| 2   | The Verge      | RSS  | ✅ 可用 |
| 3   | TechCrunch     | RSS  | ✅ 可用 |

## 广告过滤

### 过滤策略

采集阶段使用**多维度综合评分**（`is_advertisement()`），不走关键词一票否决：

| 维度  | 条件                     | 分值      | 说明                           |
| --- | ---------------------- | ------- | ---------------------------- |
| A   | 来源自家产品词（「36氪首发」「氪星晚报」） | +60     | 直接过滤，无争议                     |
| B1  | 标题含品牌名 + 广告确认词         | +40     | 品牌在标题任意位置                    |
| B2  | 标题以品牌名开头 + 弱广告特征       | +35     | 品牌开头本身就可疑                    |
| B3  | 产品发布通用模式（不依赖品牌）        | +30     | 「充电宝版」「录音卡」「多动力版本上市」         |
| B4  | 合作推广模式                 | +25     | 「强强联手」「牵手」「达成全面合作」           |
| D   | 来源可信度低                 | +25     | 雷峰网/36氪/虎嗅来源加分               |
| E   | 财报/数据报告模式              | +20     | 一季度营收、同比增长、订单突破              |
| E2  | 活动宣传模式                 | +25     | 年会闭幕、峰会圆满闭幕                  |
| F   | **AI 保护降分**            | **-20** | 含 ACL/CVPR/开源/GitHub 等保护正常新闻 |

**判定阈值：**

- `>= 45 分`：判定为广告，直接过滤
- `30-49 分`：疑似广告，降权后排
- `< 30 分`：正常新闻

### 为什么不用关键词黑名单

通过采集 7 个数据源、125 篇真实数据分析发现：

- 「正式发布」在大模型新闻中极其常见（「xxx模型正式发布」）
- 「首发价」「X元起」「已开售」在大模型 API 套餐中也会出现
- 广告文的核心特征是**标题主语是品牌/公司**，而非某个关键词

### 广告文 vs 正常新闻

| 类型         | 标题主语     | 例子                              |
| ---------- | -------- | ------------------------------- |
| ✅ 正常 AI 新闻 | 技术/模型/会议 | 「ACL 2026｜NOSE：让AI学会「闻」...」     |
| ✅ 正常 AI 新闻 | 公司+技术    | 「DR-Venus开源：仅用10K开放数据，4B小模型...」 |
| ⚠️ 广告文     | 品牌+产品    | 「别克×火山引擎：至境E7行业首发搭载豆包大模型」       |
| ⚠️ 广告文     | 品牌+数据    | 「小鹏...订单环比提升118%」               |
| ⚠️ 广告文     | 自家产品     | 「氪星晚报｜...」「36氪首发｜...」           |

## Cron 配置

### 今日AI早报（每天 09:30，单任务两段式）

- **表达式**: `30 9 * * *`
- **sessionTarget**: `main`
- **payload.kind**: `systemEvent`

执行逻辑：cron 触发后 Claude 自动执行以下流程：

1. 运行 `python wrapper.py`（采集+生成MD+输出HIGHLIGHTS_PROMPT）
2. Claude 根据 HIGHLIGHTS_PROMPT 生成今日看点 → 替换占位符
3. 运行 `python broadcast.py`（语音播报）

```bash
# cron 命令（wrapper.py 串接采集+生成 MD，语音由 AI 阶段处理）
python wrapper.py
```

- `systemEvent` + `main session`，不会超时重试
- AI 阶段 Claude 自动生成今日看点并写入 MD
- 语音通过守护进程自动播放，不阻塞任务

## 早报格式示例

```markdown
# 🤖 AI 早报 | 2026年04月30日 星期四 09:30

> 📡 数据窗口：昨日 09:31 ~ 今日 09:30  |  共收录 15 条

---

## 🤖 模型发布
*新模型发布、版本迭代、性能突破、技术评测*

⭐⭐⭐ Transformer可以改装成Mamba了：苹果把推理成本直接打成线性
> 🕐 2026/04/22 12:02  |  📍 机器之心
>编辑｜Sia最近，苹果又整了个活儿...
>[查看原文](https://www.jiqizhixin.com/articles/2026-04-22-8)
---
```

## 输出位置

- **Markdown 文件**：`output/ai_daily_news_YYYYMMDD_HHMM.md`
- **播报文本**：`output/latest.txt`
- **最新 MD**：`output/latest.md`

## 依赖

- Python 3.8+
- requests
- feedparser
- bs4（可选，用于量子位网页解析）
- tts-switcher（统一 TTS 语音合成入口）

安装依赖：

```bash
pip install requests feedparser beautifulsoup4 edge-tts pygame
```

> 语音播报依赖 `edge-tts`（在线，默认）和 `pygame`（本地播放），均为 pip 包。
> 技能自带 TTS 依赖脚本（`data/` 目录），无需安装额外依赖即可使用。
> 高级引擎（xiaomi-mimo-tts / qwen3tts）可在 `config/tts_config.json` 中配置路径启用。

---

## 语音播报功能

### 核心架构

```
broadcast.py → tts_switcher → 当前激活的 TTS 引擎
                     ↓
              config.json 中的 active_engine
                     ↓
         xiaomi-mimo-tts（小米情感语音，默认）
         edge-tts（微软云端）
         qwen3tts（本地 GPU，克隆音色，需分段）
```

### 播报格式

- 标题含星期（如"星期五"）
- 新闻加序号，序号和标题间用顿号分隔
- 板块过渡用"接下来是"
- 随机结束语（5种）
- 无内容板块自动跳过

### 音频播放逻辑

走 TTS 队列系统（不走 pygame.mixer.music，避免 Windows 上卡住）：

1. `broadcast.py` 自己读 `config/tts_config.json`，按引擎路由直接调对应脚本
2. 生成音频后打印 `RESULT: <音频路径>`
3. `ai_daily_news.py` 解析该路径，调用 `tts_queue.py add <文本> --file <音频路径>` 交给队列
4. `ts_daemon.py` 守护进程后台消费队列并播放，使用 Windows Named Mutex 防止多实例同时播放

> ⚠️ 之前版本用 `pygame.mixer.music` 直接播放，在 Windows 上 `get_busy()` 会卡住，导致 cron session 被 SIGKILL 杀死。改走队列后 subprocess 30 秒超时，不阻塞 cron。

### broadcast.py 引擎路由（2026-04-30 更新）

`broadcast.py` 自己读 config、自己路由，不再依赖 `tts_switcher generate` 命令：

| 引擎              | 策略                                       | 失败兜底         |
| --------------- | ---------------------------------------- | ------------ |
| qwen3tts        | 逐段切分 → speak.py --output → ffmpeg 合成 WAV | → edge-tts   |
| xiaomi-mimo-tts | tts.py --no-queue --no-play 生成 MP3       | → edge-tts   |
| edge-tts        | edge_tts 直接生成 MP3                        | 无（报错返回 None） |
| 其他/未知           | → edge-tts                               | —            |

Qwen3TTS 切段规则：按 `。！？` 切分，每段独立调 `speak.py`（内部自动做数字预处理），ffmpeg concat 合成。

### 语音清洗（仅播报阶段）

转 TXT 时只做两件事：

1. **学术会议前缀去除**：动态匹配 `ICLR/NeurIPS/CVPR/AAAI/ACL/ICML/ECCV/EMNLP/IJCAI + 年份` 前缀
2. **多音字替换**：下载量→下载亮、日更→日耕（来自 `config/polyphone_map.json`）

广告词清洗已在采集阶段完成，语音阶段不再重复。.md 原文不做任何修改，所有清洗仅在 .md → .txt 时完成。

### TTS 引擎与时长

| 引擎              | 输出格式 | 说明                                   |
| --------------- | ---- | ------------------------------------ |
| xiaomi-mimo-tts | MP3  | 小米情感语音；MiMo 失败自动兜底 edge-tts          |
| edge-tts        | MP3  | 微软云端，质量高，最终兜底                        |
| qwen3tts        | WAV  | 本地 GPU，逐段生成+ffmpeg合成；失败自动兜底 edge-tts |

> 引擎选择逻辑在 `broadcast.py` 的 `generate_audio()` 函数内，读 `config/tts_config.json` 的 `active_engine` 决定（`auto` 模式自动探测可用引擎）。

### 播报示例

```
AI早报，2026年4月30日星期四。

模型发布板块，1、DeepSeek发布V3模型，性能超越GPT-4。

接下来是产品应用板块。1、百度文心一言用户破亿。2、阿里通义千问上线新功能...

以上就是今天的AI早报，感谢收听，明天见。
```

---

## 🔧 备选方案：分段合成（偶发音频重复时启用）

> **触发条件**：MiMo TTS 偶发返回重复/过长音频时（约 10-20% 概率），启用本方案。

### 问题背景

MiMo API 偶尔对长文本（>400字）返回内容重复的音频。
表现为音频文件异常偏大（正常 1010-1042KB，异常 1186-1601KB），时长多 20-30 秒。

### 备选方案：按板块分段合成

**核心思路**：不再一次性传入整篇早报，而是按板块分别合成，最后合并入队。

```python
# broadcast.py 的 generate_audio() 中增加长度检查
MAX_MIMO_LENGTH = 300  # MiMo 安全文本长度

if engine_name == "xiaomi-mimo-tts" and len(text) > MAX_MIMO_LENGTH:
    # 降级到 edge-tts，或走分段合成
    return _generate_segmented(text, output_dir)

# 分段合成函数
def _generate_segmented(text, output_dir):
    """按句号切分，每段 < 300 字，逐段合成后 ffmpeg 合并"""
    segments = _split_by_sentence(text, max_len=300)
    audio_paths = []
    for seg in segments:
        path = _generate_with_mimo(seg, output_dir)
        if path:
            audio_paths.append(path)
    # ffmpeg concat 合并
    return _merge_audio_files(audio_paths, output_dir)
```

**各段独立保留情绪 instruct（Qwen3TTS 分支）**，合并后情绪过渡自然。

**优点**：

- 彻底规避 MiMo 长文本重复 bug
- 每段时长可控，便于定位问题
- 段间有自然停顿，听感更好

**缺点**：

- 合成时间变长（多段串行）
- 需要 ffmpeg 合并步骤

### 启用方式

1. 在 `broadcast.py` 中取消 `_generate_segmented()` 的注释
2. 修改 `generate_audio()` 中的 `MAX_MIMO_LENGTH` 阈值（默认 300）
3. 重启守护进程即可生效

---

## 📝 更新历史

| 日期         | 变更                                                                                                                                                                    |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 2026-05-05 | **v2.2 免费 API + 全自动**：新增 free_providers.py（智谱 GLM-4.7-Flash 免费API，支持回退+故障标记）；wrapper.py 免费Key可用时自动跑 broadcast 完成全流程；音频互斥改为多源可配置（WorkBuddy / OpenClaw 等）；generate_final.py 集成免费厂商调用；新增 config/free_api.env.example |
| 2026-04-30 | **MiMo 音频查找修复**：broadcast.py 的 MiMo 分支从直接调 tts.py 改为 import tts_switcher.generate_audio_file()，复用其三层 fallback 逻辑（音频保存于→合成完成→TEMP/mimo目录搜索），解决 MiMo 输出文件名不固定导致的文件找不到问题 |
| 2026-04-30 | **Cron 合并**：从两个独立 cron（09:30 文本 + 09:35 语音）合并为单个 `systemEvent` 任务，用 `&&` 串联两段，文本完成立刻跑语音，不再超时重试；SKILL.md 手动运行章节新增两段式播报规范                                               |
| 2026-04-30 | **broadcast.py 引擎路由重构**：`generate_audio()` 自己读 config.json 路由，不再依赖 `tts_switcher generate` 命令；各引擎失败自动兜底 edge-tts；MiMo 输出解析改用 GBK 解码                        |
| 2026-04-30 | **广告过滤升级**：从关键词黑名单升级为多维度综合评分（7 个维度，实测 96%+ 准确率）；广告过滤前移到采集阶段；broadcast.py 的 clean_title() 简化，只保留学术会议前缀去除和多音字替换                                                         |
| 2026-04-30 | **流程解耦**：ai_daily_news.py 加 `--text-only` 模式，文本早报和语音播报拆成两个独立 cron；stdout 早报摘要用 `=== DAILY_REPORT_START/END ===` 标记包裹，方便 cron AI 解析                                    |
| 2026-04-30 | **Qwen3TTS 数字读法修复**：speak.py 新增 `preprocess_text_for_qwen3tts()`，阿拉伯数字序号（1、2、3）自动转中文（一、二、三），修复 Qwen3TTS 把数字读成英文的问题；broadcast.py 的 Qwen3TTS 分支改为逐段生成 + ffmpeg 合成       |
| 2026-04-30 | **Cron 命令串联修复**：PowerShell 5.x 不支持 `&&`，导致 cron 中 broadcast.py 从未执行；改为 `; if ($?) { }` 语法，测试通过                                                                        |
| 2026-04-29 | 复查修复：修正 SKILL.md 中 Cron 配置为实际格式（agentTurn + isolated）；发现生成了两份早报（09:31 和 11:08），根因是第一次运行超时（300秒）后触发重试，且脚本无防重复机制                                                        |
| 2026-04-28 | 播放逻辑重构：原 pygame.mixer.music 直接播放改为走 TTS 队列系统（tts_daemon.py），subprocess 30 秒超时，避免 cron session 被 SIGKILL 杀死                                                            |
| 2026-04-28 | broadcast.py 解析 `RESULT:` 行获取音频路径，ai_daily_news.py 不再复制到 latest.mp3/latest.wav                                                                                        |
