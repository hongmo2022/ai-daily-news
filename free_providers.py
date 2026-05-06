# -*- coding: utf-8 -*-
"""
免费 AI 厂商自动切换模块 v2.1

收录真正免费、只需注册即可使用的厂商：
  - 智谱 GLM-4.7-Flash   open.bigmodel.cn    免费模型

用法：
  1. 在 open.bigmodel.cn 注册 → 获取 API Key → 设置环境变量 ZHIPU_API_KEY
  2. 如需扩展其他厂商，在 _build_providers() 中添加即可

失效逻辑：401/403 → 标记 dead（24h 后重试）；429 区分临时过载（不标记）和真实限流
"""
import os
import sys
import json
import time
from datetime import datetime, timezone, timedelta
from typing import Optional
from dataclasses import dataclass, field

import requests

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SKILL_DIR, 'output')
STATUS_FILE = os.path.join(OUTPUT_DIR, 'free_provider_status.json')
DEAD_TIMEOUT_HOURS = 24
REQUEST_TIMEOUT = 30
MAX_RETRIES = 2

# ===================== 用户引导文案 =====================

GUIDE_TEXT = """
╔══════════════════════════════════════════════════════════════╗
║  今日看点自动生成失败 — 免费厂商不可用                        ║
║                                                              ║
║  只需 2 分钟配置免费 API Key：                               ║
║                                                              ║
║  智谱 GLM-4.7-Flash（免费模型）                              ║
║    1. 打开 https://open.bigmodel.cn 注册（手机号即可）        ║
║    2. 右上角 → API Keys → 创建 API Key                       ║
║    3. 运行：set ZHIPU_API_KEY=你的key                         ║
║                                                              ║
║  配好后重新运行 wrapper.py 即可自动生成今日看点。             ║
╚══════════════════════════════════════════════════════════════╝
"""


# ===================== 故障状态管理 =====================

def _load_status() -> dict:
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {'dead_list': {}, 'last_success': None, 'updated': None}


def _save_status(status: dict):
    status['updated'] = datetime.now(timezone(timedelta(hours=8))).isoformat()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(STATUS_FILE, 'w', encoding='utf-8') as f:
        json.dump(status, f, ensure_ascii=False, indent=2)


def _is_dead_expired(timestamp_str: str) -> bool:
    try:
        dead_since = datetime.fromisoformat(timestamp_str)
        return datetime.now(timezone(timedelta(hours=8))) > dead_since + timedelta(hours=DEAD_TIMEOUT_HOURS)
    except Exception:
        return True


# ===================== 自定义异常 =====================

class ProviderError(Exception):
    """厂商暂时不可用"""

class ProviderOverloadError(ProviderError):
    """临时过载，不标记失效"""

class ProviderAuthError(ProviderError):
    """API Key 无效或过期"""

class ProviderRateLimitError(ProviderError):
    """触发频率限制"""


# ===================== 厂商基类 =====================

@dataclass
class ProviderConfig:
    name: str
    priority: int
    endpoint: str
    model: str
    env_var: str
    signup_url: str
    description: str = ''
    extra_headers: dict = field(default_factory=dict)


class FreeProvider:
    """免费厂商基类，子类只需覆盖 config"""

    config: ProviderConfig
    _skip_reason: Optional[str] = None

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Content-Type': 'application/json',
            **self.config.extra_headers,
        })

    def _setup_auth(self):
        """子类覆盖：设置鉴权 header"""
        api_key = os.environ.get(self.config.env_var, '')
        if api_key:
            self.session.headers['Authorization'] = f'Bearer {api_key}'
        else:
            self._skip_reason = f'未设置 {self.config.env_var} 环境变量\n  注册获取免费 Key: {self.config.signup_url}'

    def _parse_response(self, resp: requests.Response) -> str:
        """从 OpenAI 兼容格式提取文本"""
        data = resp.json()
        if 'choices' in data:
            return data['choices'][0]['message']['content']
        raise ProviderError(f'无法解析响应: {str(data)[:200]}')

    def call(self, system_prompt: str, user_prompt: str) -> str:
        if self._skip_reason:
            raise ProviderError(self._skip_reason)

        payload = {
            'model': self.config.model,
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ],
            'temperature': 0.7,
            'max_tokens': 800,
            'stream': False,
        }

        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = self.session.post(
                    self.config.endpoint,
                    json=payload,
                    timeout=REQUEST_TIMEOUT,
                )
                if resp.status_code == 200:
                    return self._parse_response(resp)
                if resp.status_code == 429:
                    # 区分临时过载（1305）和真实限流
                    try:
                        err_data = resp.json()
                        err_code = str(err_data.get('error', {}).get('code', ''))
                    except Exception:
                        err_code = ''
                    if err_code == '1305':
                        raise ProviderOverloadError(f'{self.config.name} 当前访问量过大，稍后再试')
                    else:
                        raise ProviderRateLimitError(f'{self.config.name} 429 频率限制: {resp.text[:150]}')
                if resp.status_code in (401, 403):
                    raise ProviderAuthError(
                        f'{self.config.name} {resp.status_code} Key 无效，请重新获取\n'
                        f'  注册地址: {self.config.signup_url}'
                    )
                last_error = f'HTTP {resp.status_code}: {resp.text[:200]}'
            except requests.Timeout:
                last_error = f'{self.config.name} 请求超时'
            except (ProviderRateLimitError, ProviderAuthError):
                raise
            except ProviderOverloadError:
                raise  # 不重试，让外层切换模型  # 过载等待更久
            except ProviderError:
                raise
            except Exception as e:
                last_error = f'{self.config.name}: {e}'

            if attempt < MAX_RETRIES - 1:
                time.sleep(2)

        raise ProviderError(last_error)


# ===================== 具体厂商实现 =====================

class ZhipuProvider(FreeProvider):
    """智谱 GLM-4.7-Flash — 最新免费模型，200K 上下文；过载时回退 glm-4-flash"""
    config = ProviderConfig(
        name='zhipu',
        priority=1,
        endpoint='https://open.bigmodel.cn/api/paas/v4/chat/completions',
        model='glm-4.7-flash',
        env_var='ZHIPU_API_KEY',
        signup_url='https://open.bigmodel.cn',
        description='智谱 GLM-4.7-Flash（免费）',
    )

    FALLBACK_MODELS = ['glm-4-flash']

    def __init__(self):
        super().__init__()
        self._setup_auth()

    def call(self, system_prompt: str, user_prompt: str) -> str:
        # 尝试主模型 + 回退模型
        models_to_try = [self.config.model] + self.FALLBACK_MODELS
        last_error = None
        for model in models_to_try:
            try:
                result = self._call_with_model(model, system_prompt, user_prompt)
                if result and len(result.strip()) >= 20:
                    return result
                # 内容过短也触发回退
                if model != models_to_try[-1]:
                    print(f'  [free] {model} 返回内容过短，回退 {models_to_try[models_to_try.index(model)+1]}...')
                    time.sleep(2)
                    continue
                last_error = f'{model} 返回内容过短'
            except ProviderOverloadError as e:
                last_error = str(e)
                if model != models_to_try[-1]:
                    print(f'  [free] {model} 过载，回退 {models_to_try[models_to_try.index(model)+1]}...')
                    time.sleep(2)
                continue
        raise ProviderError(last_error or '所有模型均失败')

    def _call_with_model(self, model: str, system_prompt: str, user_prompt: str) -> str:
        if self._skip_reason:
            raise ProviderError(self._skip_reason)

        payload = {
            'model': model,
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ],
            'temperature': 0.7,
            'max_tokens': 800,
            'stream': False,
        }

        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = self.session.post(
                    self.config.endpoint,
                    json=payload,
                    timeout=REQUEST_TIMEOUT,
                )
                if resp.status_code == 200:
                    return self._parse_response(resp)
                if resp.status_code == 429:
                    try:
                        err_data = resp.json()
                        err_code = str(err_data.get('error', {}).get('code', ''))
                    except Exception:
                        err_code = ''
                    if err_code == '1305':
                        raise ProviderOverloadError(f'{self.config.name} {model} 当前访问量过大')
                    else:
                        raise ProviderRateLimitError(f'{self.config.name} 429 频率限制: {resp.text[:150]}')
                if resp.status_code in (401, 403):
                    raise ProviderAuthError(
                        f'{self.config.name} {resp.status_code} Key 无效，请重新获取\n'
                        f'  注册地址: {self.config.signup_url}'
                    )
                last_error = f'HTTP {resp.status_code}: {resp.text[:200]}'
            except requests.Timeout:
                last_error = f'{self.config.name} 请求超时'
            except (ProviderRateLimitError, ProviderAuthError):
                raise
            except ProviderOverloadError:
                raise  # 不重试，让外层切换模型
            except ProviderError:
                raise
            except Exception as e:
                last_error = f'{self.config.name}: {e}'

            if attempt < MAX_RETRIES - 1:
                time.sleep(2)

        raise ProviderError(last_error)



# ===================== 厂商管理器 =====================

class ProviderManager:
    """按优先级+状态选择和切换厂商"""

    def __init__(self):
        self.status = _load_status()
        self._build_providers()

    def _build_providers(self):
        all_providers = [ZhipuProvider()]

        dead_list = self.status.get('dead_list', {})
        last_success = self.status.get('last_success')

        alive = []
        dead = []
        for p in all_providers:
            if p.config.name in dead_list:
                entry = dead_list[p.config.name]
                if _is_dead_expired(entry.get('since', '')):
                    print(f'  [free] {p.config.name} 失效已超24h，重新尝试')
                else:
                    dead.append(p)
                    continue
            alive.append(p)

        def sort_key(p):
            is_last = 0 if p.config.name == last_success else 1
            return (is_last, p.config.priority)

        alive.sort(key=sort_key)

        self.alive_providers = alive
        self.dead_providers = dead
        self.total = len(all_providers)

    def _mark_dead(self, provider: FreeProvider, error: str):
        dead_list = self.status.setdefault('dead_list', {})
        dead_list[provider.config.name] = {
            'since': datetime.now(timezone(timedelta(hours=8))).isoformat(),
            'error': str(error)[:300],
        }
        _save_status(self.status)
        print(f'  [free] ✗ {provider.config.name} 已标记失效: {error[:120]}')

    def _mark_success(self, name: str):
        self.status['last_success'] = name
        self.status.setdefault('dead_list', {}).pop(name, None)
        _save_status(self.status)

    def generate_highlights(
        self,
        articles_summary: str,
        period_name: str,
        greeting: str,
        holiday_name: Optional[str] = None,
        holiday_day: Optional[int] = None,
        holiday_total: Optional[int] = None,
    ) -> Optional[str]:
        """遍历厂商生成今日看点，全部失败返回 None"""

        if not articles_summary.strip():
            print('  [free] 无新闻摘要，跳过生成')
            return None

        # 构建 prompt
        holiday_context = ''
        if holiday_name:
            holiday_context = (
                f'当前节日：{holiday_name}（假期第{holiday_day}天，共{holiday_total}天）。'
                f'请在问候中体现节日氛围。'
            )

        system_prompt = '你是一位专业的AI新闻编辑，请根据以下新闻摘要生成一段"今日看点"总结。'

        user_prompt = f'''请根据以下新闻列表生成一段"今日看点"总结。

时段：{period_name}
问候语开头：{greeting}
{holiday_context}

要求：
- 开头用"{greeting}"打招呼
- 用2-4句话概括今天最值得关注的新闻亮点
- 不要列序号，不要读标题，用总结性语言
- 风格：简洁、自然、有信息量，像朋友聊天一样
- 总字数控制在100-200字
- 绝对不要出现与当前时段不符的问候

今日新闻摘要：
{articles_summary}

请直接输出总结文本。'''

        total_available = len(self.alive_providers)
        print(f'  [free] 可用: {total_available}/{self.total}, dead: {len(self.dead_providers)}')

        for i, provider in enumerate(self.alive_providers):
            name = provider.config.name
            try:
                print(f'  [free] [{i+1}/{total_available}] 尝试 {name} ({provider.config.description})...')
                result = provider.call(system_prompt, user_prompt)
                if result and len(result.strip()) >= 20:
                    self._mark_success(name)
                    print(f'  [free] ✓ {name} 生成成功 ({len(result)} 字)')
                    return result.strip()
                else:
                    print(f'  [free] ✗ {name} 返回内容过短: {result[:100] if result else "空"}')
                    continue
            except (ProviderRateLimitError, ProviderAuthError) as e:
                self._mark_dead(provider, str(e))
                continue
            except ProviderError as e:
                print(f'  [free] ✗ {name}: {e}')
                continue
            except Exception as e:
                print(f'  [free] ✗ {name} 未知错误: {e}')
                continue

        # 全部失败 —— 打印用户引导
        print(GUIDE_TEXT, file=sys.stderr)
        return None


# ===================== 顶层 API =====================

_manager: Optional[ProviderManager] = None


def generate_highlights(
    articles_summary: str,
    period_name: str = '',
    greeting: str = '早上好大哥！',
    holiday_name: Optional[str] = None,
    holiday_day: Optional[int] = None,
    holiday_total: Optional[int] = None,
) -> Optional[str]:
    """
    使用免费厂商生成今日看点。
    返回生成的文本，或 None（需要手动填写）。
    """
    global _manager
    if _manager is None:
        _manager = ProviderManager()
    else:
        _manager._build_providers()

    return _manager.generate_highlights(
        articles_summary=articles_summary,
        period_name=period_name,
        greeting=greeting,
        holiday_name=holiday_name,
        holiday_day=holiday_day,
        holiday_total=holiday_total,
    )


# ===================== 自检 =====================

def check_all_providers() -> Dict[str, str]:
    """快速检测所有厂商连通性"""
    manager = ProviderManager()
    results = {}
    test_system = '你是一个助手。'
    test_user = '只回复OK两个字母，不要其他内容。'

    for provider in manager.alive_providers + manager.dead_providers:
        try:
            result = provider.call(test_system, test_user)
            results[provider.config.name] = f'OK ({len(result)} chars)'
        except Exception as e:
            results[provider.config.name] = f'FAIL — {e}'

    return results


if __name__ == '__main__':
    print('=== 免费厂商连通性检测 ===')
    print()
    results = check_all_providers()
    for name, status in results.items():
        flag = '✓' if status.startswith('OK') else '✗'
        print(f'  {flag} {name}: {status}')

    all_ok = all(v.startswith('OK') for v in results.values())
    if not all_ok:
        print()
        print('配置免费 Key 即可启用自动生成：')
        print('  set ZHIPU_API_KEY=你的key      # https://open.bigmodel.cn')
