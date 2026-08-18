"""向量化。走 DashScope 原生接口（而非 OpenAI 兼容接口），因为只有原生接口
支持 text_type 参数 —— 文献检索是非对称任务（短问句 vs 长段落），入库用
document、查询用 query，召回质量明显好于两边都用默认值。"""
from __future__ import annotations

import time
from typing import List

import httpx
import numpy as np

from . import config


class EmbedError(RuntimeError):
    pass


def _post(texts: List[str], text_type: str, timeout: float) -> List[List[float]]:
    if not config.DASHSCOPE_API_KEY:
        raise EmbedError("未配置 DASHSCOPE_API_KEY，无法向量化。检索会自动降级为纯关键词模式。")
    payload = {
        "model": config.EMBED_MODEL,
        "input": {"texts": texts},
        "parameters": {
            "dimension": config.EMBED_DIM,
            "text_type": text_type,
            "output_type": "dense",
        },
    }
    r = httpx.post(
        config.DASHSCOPE_EMBED_URL,
        headers={
            "Authorization": f"Bearer {config.DASHSCOPE_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout,
    )
    if r.status_code != 200:
        raise EmbedError(f"HTTP {r.status_code}: {r.text[:300]}")
    body = r.json()
    if body.get("code"):
        raise EmbedError(f"{body['code']}: {body.get('message', '')}")
    items = body["output"]["embeddings"]
    # 接口不保证返回顺序，必须按 text_index 归位
    items.sort(key=lambda x: x["text_index"])
    if len(items) != len(texts):
        raise EmbedError(f"返回条数不匹配：请求 {len(texts)}，返回 {len(items)}")
    return [it["embedding"] for it in items]


def embed_batch(
    texts: List[str],
    text_type: str = "document",
    retries: int = 5,
    timeout: float = 60.0,
) -> np.ndarray:
    """向量化一批文本（≤10 条），失败按指数退避重试。返回 (n, dim) float32，已 L2 归一化。"""
    if len(texts) > config.EMBED_BATCH:
        raise ValueError(f"单次最多 {config.EMBED_BATCH} 条，收到 {len(texts)} 条")
    last = None
    for attempt in range(retries):
        try:
            vecs = _post(texts, text_type, timeout)
            return l2_normalize(np.asarray(vecs, dtype=np.float32))
        except Exception as e:  # noqa: BLE001 — 网络/限流/服务端错误都重试
            last = e
            if attempt < retries - 1:
                time.sleep(min(2 ** attempt, 30))
    raise EmbedError(f"重试 {retries} 次仍失败：{last}")


def embed_query(text: str) -> np.ndarray:
    """向量化单条查询，返回 (dim,) float32 已归一化。"""
    return embed_batch([text[: config.EMBED_MAX_CHARS]], text_type="query")[0]


def l2_normalize(m: np.ndarray) -> np.ndarray:
    """归一化后余弦相似度 == 点积，检索时一次矩阵乘法就出全部分数。"""
    m = np.asarray(m, dtype=np.float32)
    norms = np.linalg.norm(m, axis=-1, keepdims=True)
    np.maximum(norms, 1e-12, out=norms)  # 防零向量除零
    return m / norms
