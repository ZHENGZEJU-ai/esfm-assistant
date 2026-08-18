"""对话模型层。DeepSeek 和通义千问都提供 OpenAI 兼容接口，所以切换只是换
base_url + model 两个环境变量的事，业务代码完全不用动。"""
from __future__ import annotations

import logging
from typing import Iterator, List, Optional

from openai import OpenAI

from . import config

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


def _client(provider: Optional[str] = None):
    name = provider or config.LLM_PROVIDER
    cfg = config.PROVIDERS.get(name)
    if not cfg:
        raise LLMError(f"未知 provider: {name}，可选 {list(config.PROVIDERS)}")
    if not cfg["api_key"]:
        raise LLMError(f"provider={name} 未配置 API Key，请检查 .env")
    return OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"], timeout=120.0), cfg["model"]


def stream_chat(messages: List[dict], provider: Optional[str] = None,
                temperature: float = 0.2) -> Iterator[str]:
    """流式输出。temperature 压到 0.2 —— 文献问答要的是忠实复述，不是创造性发挥。"""
    client, model = _client(provider)
    resp = client.chat.completions.create(
        model=model, messages=messages, temperature=temperature, stream=True,
    )
    for chunk in resp:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


def chat(messages: List[dict], provider: Optional[str] = None,
         temperature: float = 0.2, max_tokens: int = 512) -> str:
    client, model = _client(provider)
    r = client.chat.completions.create(
        model=model, messages=messages, temperature=temperature, max_tokens=max_tokens,
    )
    return (r.choices[0].message.content or "").strip()


def expand_query(question: str) -> str:
    """把中文问题扩成英文检索词，拼回原问题一起检索。失败就原样返回，不阻断主流程。"""
    from .prompts import REWRITE_SYSTEM

    try:
        kw = chat(
            [{"role": "system", "content": REWRITE_SYSTEM}, {"role": "user", "content": question}],
            temperature=0.0, max_tokens=120,
        )
        return f"{question} {kw}" if kw else question
    except Exception as e:  # noqa: BLE001
        log.warning("查询扩写失败，用原问题检索：%s", e)
        return question


def available() -> dict:
    return {n: bool(c["api_key"]) for n, c in config.PROVIDERS.items()}
