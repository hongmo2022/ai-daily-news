# 🤖 AI 每日早报 (ai-daily-news)

> v2.2 — 免费 API 自动生成今日看点 + 全自动无人值守 + 多源音频互斥

## 功能概述

每天 09:30 自动采集过去 24 小时的 AI 科技新闻，按六大分类整理成精美的 Markdown 早报，并支持语音播报生成。

### 今日看点自动生成

配置一个免费大模型 API Key 后，wrapper 全自动运行，无需 AI Agent 介入：

| 厂商  | 模型            | 费用       | 注册地址             |
| --- | ------------- | -------- | ---------------- |
| 智谱  | GLM-4.7-Flash | **免费模型** | open.bigmodel.cn |

详见 `config/free_api.env.example`。

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. （可选）配置免费 API 自动生成今日看点

```bash
# 设置环境变量
set ZHIPU_API_KEY=你的key       # https://open.bigmodel.cn
```

### 3. 运行

```bash
# 一键全流程（已配免费 Key 时全自动，否则提示手动填看点）
python wrapper.py

# 只生成文本早报
python ai_daily_news.py --text-only

# 只生成语音播报（基于 latest.md）
python broadcast.py
```

## 核心特性

- **多源聚合**：机器之心 API + 量子位 + 36氪 + 雷峰网 + 虎嗅 + Anthropic Blog + The Verge + TechCrunch
- **六大分类**：模型发布 / 产品应用 / 开发生态 / 资本动态 / 政策法规 / 前瞻传闻
- **智能广告过滤**：多维度综合评分（7 个维度，实测 96%+ 准确率），采集阶段直接过滤
- **权重学习**：根据你的反馈自动调整来源权重
- **语音播报**：支持 edge-tts / xiaomi-mimo-tts / qwen3tts 等引擎（可选）
- **防重复机制**：同一天不会重复生成
- **免费 API 自动生成看点**：智谱 GLM-4.7-Flash，无需付费
- **全自动无人值守**：免费 Key 可用时 wrapper.py 自动完成采集→看点→播报三阶段
- **多源音频互斥**：可配置检测 WorkBuddy / OpenClaw 等 agent 的语音播放，避免冲突

## 六大分类

| #   | 分类   | emoji | 说明                      |
| --- | ---- | ----- | ----------------------- |
| 1   | 模型发布 | 🤖    | 新模型发布、版本迭代、性能突破、技术评测    |
| 2   | 产品应用 | 🚀    | 产品上线、功能更新、商业化落地         |
| 3   | 开发生态 | 🛠️   | 开源、SDK、API、开发者工具、GitHub |
| 4   | 资本动态 | 💰    | 融资、IPO、估值、高管变动、收购       |
| 5   | 政策法规 | ⚖️    | 监管、安全、伦理、法律、审查          |
| 6   | 前瞻传闻 | 🔮    | 爆料、计划、预计、或将（可信度可略低）     |

## 文件结构

```
ai-daily-news/
├── ai_daily_news.py      # 主脚本：新闻采集 + 广告过滤 + MD 生成
├── broadcast.py          # 语音播报：MD → TXT → MP3/WAV（按引擎路由）
├── generate_final.py     # 生成最终 MD（免费API自动看点 或 输出HIGHLIGHTS_PROMPT）
├── free_providers.py     # 免费厂商自动切换模块（智谱，fallback + 故障标记）
├── news_sources.py       # 数据源采集模块（8个来源并发采集）
├── wrapper.py            # 一键入口（已配免费Key全自动，否则提示手动）
├── requirements.txt      # Python 依赖
├── LICENSE               # MIT 协议
├── README.md             # 本文档
├── SKILL.md              # 技能说明文档（OpenClaw 用）
├── .gitignore            # Git 忽略规则
├── config/
│   ├── ad_filter.json           # 广告词过滤表
│   ├── polyphone_map.json       # 多音字映射表（仅播报用）
│   ├── tts_config.json          # TTS 引擎 + 音频互斥源配置
│   ├── tts_duration_limits.json # TTS 时长限制规则
│   └── free_api.env.example     # 免费 API Key 配置模板
├── data/
│  ├── tts_queue.py             # TTS 队列管理器（音频排队 + 多源互斥检测）
│  ├── speak.py                 # Qwen3TTS 调用入口
│  ├── tts_switcher.py          # 统一 TTS 切换器
│  ├── _paths.py                # 统一路径配置
│   └── holiday_cache.json       # 节日缓存（2025-2035）
└── output/               # 生成的早报（运行时生成）
    ├── ai_daily_news_YYYYMMDD_HHMM.md  # 每日 MD 原稿
    ├── latest.md               # 最新 MD
    ├── latest.txt              # 播报纯文本
    └── 音频文件                # TTS 引擎生成的 MP3/WAV
```

## 命令行用法

### Wrapper 一键运行（推荐）

```bash
python wrapper.py
```

已配免费 Key → 自动采集 + 生成看点 + 语音播报三阶段全自动。

未配免费 Key → 采集 + 生成 MD + 输出 HIGHLIGHTS_PROMPT，等待 AI Agent 手动处理。

> ⚠️ **关键规则**：采集失败时不要继续播报，避免用旧文件凑合。

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

# 指定 TTS 引擎（覆盖配置）
python broadcast.py --engine edge-tts
python broadcast.py --engine qwen3tts
python broadcast.py --engine xiaomi-mimo-tts

# 仅测试数据采集
python news_sources.py
```

## 多源音频互斥配置

如果你同时运行了其他 TTS 语音播报系统（如 WorkBuddy、OpenClaw 等），两个系统的音频可能**同时播放**互相干扰。配置互斥后，本系统播报前会自动检测并等待对方播完。

### 我怎么知道需要配置？

运行播报时如果出现"两个声音叠在一起"或者"AI 早报盖掉了其他语音"，就需要配置互斥。

### 三步配置

**第 1 步**：找到另一套系统的 playing / queue 文件位置。常见系统的默认路径：

| 系统        | playing 文件                           | queue 文件                           |
| --------- | ------------------------------------ | ---------------------------------- |
| WorkBuddy | `workbuddy 技能目录/output/playing.json` | `workbuddy 技能目录/output/queue.json` |
| OpenClaw  | 查看 OpenClaw TTS 技能文档                 | 同上                                 |
| 自定义系统     | 联系开发者或查看源代码                          | 同上                                 |

> 如果对方系统只提供一种状态文件，只填一个即可。playing 优先于 queue。

**第 2 步**：打开 `config/tts_config.json`，找到 `audio_mutex_sources`，将你要互斥的系统 `enabled` 设为 `true`，填入文件完整路径：

```json
"audio_mutex_sources": [
  {
    "name": "WorkBuddy",
    "enabled": true,
    "playing_file": "C:\\Users\\你的用户名\\.claude\\skills\\workbuddy\\output\\playing.json",
    "queue_file": "C:\\Users\\你的用户名\\.claude\\skills\\workbuddy\\output\\queue.json"
  },
  {
    "name": "OpenClaw",
    "enabled": false,
    "playing_file": "",
    "queue_file": ""
  }
]
```

**第 3 步**：重新运行播报。日志中出现 `⏳ WorkBuddy 正在播放，预计还需 Xs，智能等待...` 即配置生效。

### 自动检测（让 AI Agent 执行）

如果你不确定机上有哪些系统在跑，把下面这条发给 AI Agent 即可自动检测：

```powershell
# 一键扫描机上所有 TTS 语音系统
Write-Host "=== 1. 已知系统状态文件 ==="
@(
    "$env:USERPROFILE\.claude\skills\workbuddy\output\playing.json",
    "$env:USERPROFILE\.claude\skills\workbuddy\output\queue.json",
    "$env:USERPROFILE\.openclaw\tts\playing.json",
    "$env:USERPROFILE\.openclaw\tts\queue.json"
) | ForEach-Object { if (Test-Path $_) { Write-Host "  [FOUND] $_" } else { Write-Host "  [  -  ] $_" } }

Write-Host "`n=== 2. 含 TTS 关键词的 Python 进程 ==="
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | 
    Where-Object { $_.CommandLine -match 'tts|speak|queue|pygame|mixer|edge_tts|play' } |
    Select-Object ProcessId, @{N='CommandLine';E={$_.CommandLine.Substring(0, [Math]::Min(200, $_.CommandLine.Length))}} |
    Format-Table -AutoSize

Write-Host "`n=== 3. 音频设备活跃会话 ==="
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'wmplayer|groove|vlc|mpv|Spotify|QQMusic|edge_tts|pygame' } |
    Select-Object ProcessId, Name, @{N='CommandLine';E={if($_.CommandLine){$_.CommandLine.Substring(0,[Math]::Min(150,$_.CommandLine.Length))}else{''}}} |
    Format-Table -AutoSize
```

AI Agent 会根据扫描结果告诉你哪些系统需要互斥，以及对应的文件路径。

---

## 数据源

### 国内源

| 优先级 | 数据源  | 类型   | 状态   | 广告比例               |
| --- | ---- | ---- | ---- | ------------------ |
| 1   | 机器之心 | API  | ✅ 可用 | ~20%（产品发布软文）       |
| 2   | 量子位  | 网页爬虫 | ✅ 可用 | 低                  |
| 3   | 36氪  | RSS  | ✅ 可用 | ~50%（含自家推广 + 非 AI） |
| 4   | 雷峰网  | RSS  | ✅ 可用 | ~40%（车企软文重灾区）      |
| 5   | 虎嗅   | RSS  | ✅ 可用 | ~90%（几乎全非 AI）      |

### 国际源

| 优先级 | 数据源            | 类型   | 状态   |
| --- | -------------- | ---- | ---- |
| 1   | Anthropic Blog | 网页爬虫 | ✅ 可用 |
| 2   | The Verge      | RSS  | ✅ 可用 |
| 3   | TechCrunch     | RSS  | ✅ 可用 |

## 时间窗口

- **数据范围**：昨天 09:31 ~ 今天 09:30（北京时区，UTC+8）
- **生成时间**：每天 09:30（cron 定时）
- **新闻条数**：目标 10-20 条（按内容质量动态分配）

## 广告过滤

采集阶段使用**多维度综合评分**（`is_advertisement()`），不走关键词一票否决。

通过采集 7 个数据源、125 篇真实数据分析发现：

- 「正式发布」在大模型新闻中极其常见（「xxx模型正式发布」）
- 广告文的核心特征是**标题主语是品牌/公司**，而非某个关键词

### 评分维度

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

**判定阈值**：

- `>= 45 分`：判定为广告，直接过滤
- `30-49 分`：疑似广告，降权后排
- `< 30 分`：正常新闻

### 广告文 vs 正常新闻

| 类型         | 标题主语     | 例子                              |
| ---------- | -------- | ------------------------------- |
| ✅ 正常 AI 新闻 | 技术/模型/会议 | 「ACL 2026｜NOSE：让AI学会「闻」...」     |
| ✅ 正常 AI 新闻 | 公司+技术    | 「DR-Venus开源：仅用10K开放数据，4B小模型...」 |
| ⚠️ 广告文     | 品牌+产品    | 「别克×火山引擎：至境E7行业首发搭载豆包大模型」       |
| ⚠️ 广告文     | 品牌+数据    | 「小鹏...订单环比提升118%」               |
| ⚠️ 广告文     | 自家产品     | 「氪星晚报｜...」「36氪首发｜...」           |

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

## 配置说明

### 免费 API Key（自动生成今日看点）

设为环境变量即可启用全自动模式：

```bash
set ZHIPU_API_KEY=你的key       # https://open.bigmodel.cn 注册获取
```

详见 `config/free_api.env.example`。

### 多源音频互斥（多 agent 环境）

如果同时使用 WorkBuddy、OpenClaw 等多个会语音播报的 agent，可在 `config/tts_config.json` 的 `audio_mutex_sources` 中配置各 agent 的播放信号文件路径。播报前会自动检测并等待其他 agent 播完。

### 环境变量

| 变量              | 默认值 | 说明                         |
| --------------- | --- | -------------------------- |
| `ZHIPU_API_KEY` | (空) | 智谱 GLM-4.7-Flash Key，免费不限量 |

| `NEWS_OUTPUT_DIR`         | `./output`                  | 早报输出目录                                  |
| `NEWS_DATA_DIR`           | `./data`                    | 数据缓存目录                                  |
| `TTS_ENGINE`              | `edge-tts`                  | 语音引擎（edge-tts/xiaomi-mimo-tts/qwen3tts） |

### Cron 配置示例

```cron
# 每天 09:30 一键全流程（已配免费 Key 时全自动）
30 9 * * * cd /path/to/ai-daily-news && python wrapper.py
```

## 语音播报

语音播报为**可选功能**。不安装 TTS 相关依赖也能正常运行文本早报。

### 核心架构

```
broadcast.py → 读取 config.json 中的 active_engine
                     ↓
    ┌────────────────┼────────────────┐
    ↓                ↓                ↓
edge-tts         xiaomi-mimo-tts    qwen3tts
(MP3, 默认)      (MP3, 情感语音)    (WAV, 克隆音色, 需分段+ffmpeg)
```

### 支持的 TTS 引擎

| 引擎              | 输出格式 | 说明                       |
| --------------- | ---- | ------------------------ |
| edge-tts        | MP3  | 微软云端，质量高，**默认引擎**，无需 GPU |
| xiaomi-mimo-tts | MP3  | 小米情感语音，需额外配置             |
| qwen3tts        | WAV  | 本地 GPU，克隆音色，需 ffmpeg 合成  |

### broadcast.py 引擎路由

`broadcast.py` 自己读 config.json 路由，不再依赖外部命令：

| 引擎              | 策略                                       | 失败兜底         |
| --------------- | ---------------------------------------- | ------------ |
| qwen3tts        | 逐段切分 → speak.py --output → ffmpeg 合成 WAV | → edge-tts   |
| xiaomi-mimo-tts | tts.py --no-queue --no-play 生成 MP3       | → edge-tts   |
| edge-tts        | edge_tts 直接生成 MP3                        | 无（报错返回 None） |
| 其他/未知           | → edge-tts                               | —            |

Qwen3TTS 切段规则：按 `。！？` 切分，每段独立调 `speak.py`（内部自动做数字预处理），ffmpeg concat 合成。各段独立保留情绪 instruct，合并后情绪过渡自然。

### 播报格式

- 标题含星期（如"星期五"）
- 新闻加序号，序号和标题间用顿号分隔
- 板块过渡用"接下来是"
- 随机结束语（5种）
- 无内容板块自动跳过

### 播报示例

```
AI早报，2026年4月30日星期四。

模型发布板块，1、DeepSeek发布V3模型，性能超越GPT-4。

接下来是产品应用板块。1、百度文心一言用户破亿。2、阿里通义千问上线新功能...

以上就是今天的AI早报，感谢收听，明天见。
```

### 语音清洗（仅播报阶段）

转 TXT 时只做两件事：

1. **学术会议前缀去除**：动态匹配 `ICLR/NeurIPS/CVPR/AAAI/ACL/ICML/ECCV/EMNLP/IJCAI + 年份` 前缀
2. **多音字替换**：下载量→下载亮、日更→日耕（来自 `config/polyphone_map.json`）

广告词清洗已在采集阶段完成，语音阶段不再重复。.md 原文不做任何修改，所有清洗仅在 .md → .txt 时完成。

### 安装 edge-tts（推荐）

```bash
pip install edge-tts
```

## 备选方案：分段合成（偶发音频重复时启用）

> **触发条件**：语音TTS 偶发返回重复/过长音频时（约 10-20% 概率），启用本方案。

语音TTS API 偶尔对长文本（>400字）返回内容重复的音频。表现为音频文件异常偏大（正常 1010-1042KB，异常 1186-1601KB），时长多 20-30 秒。

**核心思路**：不再一次性传入整篇早报，而是按板块分别合成最后合并。按句号切分，每段 < 300 字，逐段合成后 ffmpeg 合并。各段独立保留情绪 instruct（Qwen3TTS 分支），合并后情绪过渡自然。

**优点**：彻底规避长文本重复 bug；每段时长可控，便于定位问题；段间有自然停顿，听感更好。
**缺点**：合成时间变长（多段串行）；需要 ffmpeg 合并步骤。

## 输出位置

- **Markdown 文件**：`output/ai_daily_news_YYYYMMDD_HHMM.md`
- **播报文本**：`output/latest.txt`
- **最新 MD**：`output/latest.md`
- **音频文件**：`output/ai_daily_news_*.mp3` 或 `.wav`

## 依赖

- Python 3.8+
- requests
- feedparser
- bs4（用于量子位网页解析）

```bash
pip install requests feedparser beautifulsoup4
# 语音播报（可选）
pip install edge-tts
```

## 更新历史

| 日期         | 变更                                                                                                                                                     |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 2026-05-05 | **v2.2 免费 API + 全自动**：新增 free_providers.py（智谱免费API自动生成看点）；wrapper.py 免费Key可用时全自动跑三阶段；音频互斥改为多源可配置（支持 WorkBuddy / OpenClaw 等）；generate_final.py 集成免费厂商调用 |
| 2026-05-03 | **v2.0.1 GitHub 发布**：移除所有硬编码路径和隐私信息，添加 .env.example / .gitignore / LICENSE / README.md，改造为相对路径 + 环境变量配置                                                |
| 2026-04-30 | **GitHub 可分享版本发布**：移除硬编码路径，改为相对路径 + 环境变量                                                                                                               |
| 2026-04-30 | **MiMo 音频查找修复**：broadcast.py 的 MiMo 分支改为 import tts_switcher.generate_audio_file()                                                                     |
| 2026-04-30 | **Cron 合并**：从两个独立 cron 合并为单个 systemEvent 任务                                                                                                            |
| 2026-04-30 | **broadcast.py 引擎路由重构**：generate_audio() 自己读 config.json 路由                                                                                            |
| 2026-04-30 | **广告过滤升级**：从关键词黑名单升级为多维度综合评分（7 个维度，96%+ 准确率）                                                                                                           |
| 2026-04-30 | **流程解耦**：ai_daily_news.py 加 `--text-only` 模式                                                                                                           |
| 2026-04-30 | **Qwen3TTS 数字读法修复**：阿拉伯数字序号自动转中文                                                                                                                       |
| 2026-04-29 | 防重复机制修复：添加 already_generated_today() 检查                                                                                                                |
| 2026-04-28 | 播放逻辑重构：改为走 TTS 队列系统，避免 cron session 被 SIGKILL                                                                                                          |

## 许可证

MIT License - 详见 LICENSE 文件

---

> 💡 如有问题或建议，欢迎提 Issue！
