#!/usr/bin/env python3
"""开跑前的体检：确认两个 Key 都通、都能真实调用。

用法：python scripts/check_keys.py

先跑这个再跑 build_vectors.py —— 别等全量向量化跑到一半才发现 Key 配错。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402

ok = True


def line(label, good, detail=""):
    global ok
    print(f"{'  ✓' if good else '  ✗'} {label}{('  ' + detail) if detail else ''}")
    if not good:
        ok = False


print("\n[1] .env 读取")
line(".env 文件存在", (config.ROOT / ".env").exists(), str(config.ROOT / ".env"))
line("DEEPSEEK_API_KEY 已填",
     bool(config.PROVIDERS["deepseek"]["api_key"]),
     (config.PROVIDERS["deepseek"]["api_key"][:8] + "…") if config.PROVIDERS["deepseek"]["api_key"] else "空")
line("DASHSCOPE_API_KEY 已填",
     bool(config.DASHSCOPE_API_KEY),
     (config.DASHSCOPE_API_KEY[:8] + "…") if config.DASHSCOPE_API_KEY else "空 —— 没有它无法向量化")

# sk-ws- 开头 = 业务空间绑定的 Key，必须配套业务空间 URL，用公共 endpoint 会 401/403
if config.DASHSCOPE_API_KEY.startswith("sk-ws-") and "maas.aliyuncs.com" not in config.DASHSCOPE_EMBED_URL:
    print("  ! 你的 Key 是 sk-ws- 开头（业务空间绑定），但现在用的是公共 endpoint：")
    print(f"      {config.DASHSCOPE_EMBED_URL}")
    print("    若下面第 3 步报 401/403/InvalidApiKey，去百炼控制台左上角切换业务空间处复制")
    print("    WorkspaceId（形如 llm-xxxxxxxx），在 .env 里取消注释并填好 DASHSCOPE_EMBED_URL：")
    print("      DASHSCOPE_EMBED_URL=https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com"
          "/api/v1/services/embeddings/text-embedding/text-embedding")
    print("    同时把 QWEN_BASE_URL 也换成 https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1")

print("\n[2] 对话模型实测（约 ¥0.00001）")
if config.PROVIDERS[config.LLM_PROVIDER]["api_key"]:
    try:
        from app import llm

        r = llm.chat([{"role": "user", "content": "只回复两个字：收到"}], max_tokens=20)
        line(f"{config.LLM_PROVIDER} 调用成功", bool(r), f"返回 {r!r}")
    except Exception as e:  # noqa: BLE001
        line(f"{config.LLM_PROVIDER} 调用失败", False, f"{type(e).__name__}: {str(e)[:160]}")
else:
    line(f"跳过（{config.LLM_PROVIDER} 无 Key）", False)

print("\n[3] Embedding 实测（约 ¥0.000005）")
if config.DASHSCOPE_API_KEY:
    try:
        from app.embed import embed_batch

        # retries=1：体检要的是立刻看到真实错误，不是等指数退避重试 5 次
        v = embed_batch(["electrostatic film motor thrust force density",
                         "静电薄膜电机的推力密度"], text_type="document", retries=1)
        import numpy as np

        line("调用成功", True, f"shape={v.shape}")
        line("维度符合配置", v.shape[1] == config.EMBED_DIM, f"{v.shape[1]} vs {config.EMBED_DIM}")
        line("已归一化（模长≈1）", bool(np.allclose(np.linalg.norm(v, axis=1), 1.0, atol=1e-5)))
        sim = float(v[0] @ v[1])
        # 中英同义句余弦应明显高于随机（随机约 0.0-0.2）。这是向量路真正起作用的证据。
        line("中英跨语言语义对齐", sim > 0.35, f"余弦={sim:.3f}（>0.35 说明中文提问能检索英文文献）")
    except Exception as e:  # noqa: BLE001
        line("调用失败", False, f"{type(e).__name__}: {str(e)[:200]}")
        print("     常见原因：Key 错 / 未开通百炼 / 需要业务空间 URL（见 .env.example 里的 DASHSCOPE_EMBED_URL）")
else:
    line("跳过（无 DASHSCOPE_API_KEY）", False, "→ 只能用纯关键词模式，中文提问会零召回")

print("\n" + "=" * 52)
if ok:
    print("全部就绪 ✓  下一步：python scripts/build_vectors.py --limit 50")
else:
    print("有项目未通过 ✗  修好再跑 build_vectors.py，别浪费全量时间")
sys.exit(0 if ok else 1)
