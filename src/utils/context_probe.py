"""模型上下文窗口探测：优先查 /models 端点，无字段时按内置已知模型表推断"""
import json
import re
from typing import Optional
from urllib import request

# /models 响应条目里可能携带的上下文字段（OpenRouter / 部分中转服务）
_CONTEXT_KEYS = ('context_length', 'context_window', 'max_model_len',
                 'max_context_tokens', 'context_tokens', 'max_tokens')

# 内置已知模型表（子串/正则匹配，忽略大小写，更具体的放前面）
KNOWN_CONTEXT = [
    (r'gpt-3\.5', 16385),
    (r'gpt-4-turbo|gpt-4o|gpt-4\.1', 131072),
    (r'^o1|^o3|^o4', 200000),
    (r'gpt-4', 8192),
    (r'deepseek', 65536),
    (r'claude', 200000),
    (r'qwq', 32768),
    (r'qwen', 131072),
    (r'glm', 131072),
    (r'moonshot|kimi', 131072),
    (r'gemini', 1048576),
    (r'llama', 131072),
    (r'mistral', 131072),
    (r'yi-', 16384),
    (r'ernie', 131072),
    (r'hunyuan', 32768),
]


def guess_context_limit(model: str) -> Optional[int]:
    """按模型名推断上下文长度；未知模型返回 None"""
    m = (model or '').lower()
    if not m:
        return None
    for pat, tokens in KNOWN_CONTEXT:
        if re.search(pat, m):
            return tokens
    return None


def probe_context_limit(base_url: str, api_key: str, model: str,
                        timeout: float = 4.0) -> Optional[int]:
    """GET {base_url}/models，在匹配 model 的条目里找上下文字段；任何失败返回 None"""
    url = (base_url or '').strip().rstrip('/')
    if not url or not model:
        return None
    url += '/models'
    req = request.Request(url, headers={'Accept': 'application/json'})
    if api_key:
        req.add_header('Authorization', f'Bearer {api_key}')
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode('utf-8', 'ignore'))
    except Exception:
        return None
    items = data.get('data') if isinstance(data, dict) else data
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict) or item.get('id') != model:
            continue
        for key in _CONTEXT_KEYS:
            v = item.get(key)
            if isinstance(v, (int, float)) and v >= 4096:
                return int(v)
    return None
