#!/usr/bin/env python3
"""把 chunks 表全部向量化，输出 data/vectors.npy + data/vector_meta.json。

支持断点续传：中途 Ctrl-C、断网、限流都不怕，重跑会跳过已完成的批次。

用法：
    python scripts/build_vectors.py                # 续跑（默认）
    python scripts/build_vectors.py --workers 4    # 4 线程并发，约 4 倍速
    python scripts/build_vectors.py --limit 50     # 先拿 50 条试水，确认没问题再全量
    python scripts/build_vectors.py --restart      # 丢弃检查点，从头重来
    python scripts/build_vectors.py --dry-run      # 只统计条数和预估成本，不调 API

成本参考：本库 3547 段 / 573 万字符 ≈ 140 万 token，按 ¥0.0005/千 token 约 ¥0.7。
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import threading
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config          # noqa: E402
from app.embed import embed_batch, l2_normalize  # noqa: E402


def load_chunks(limit: int | None = None):
    """按 rowid 升序读取。顺序必须稳定 —— 向量文件的行序就是这个顺序。"""
    c = sqlite3.connect(str(config.DB_PATH))
    c.row_factory = sqlite3.Row
    sql = "SELECT rowid AS rid, title, text FROM chunks ORDER BY rowid"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = c.execute(sql).fetchall()
    c.close()
    rowids, texts = [], []
    for r in rows:
        title = (r["title"] or "")[:200]
        body = (r["text"] or "").strip()
        # 段落是从 PDF 单页切出来的，脱离论文标题常常没有上下文。
        # 拼上标题能明显改善"这段在讲什么"的语义表达。
        merged = f"{title}\n\n{body}" if title else body
        rowids.append(int(r["rid"]))
        texts.append(merged[: config.EMBED_MAX_CHARS])
    return np.asarray(rowids, dtype=np.int64), texts


def load_ckpt(rowids: np.ndarray, dim: int):
    """检查点与当前语料不匹配（重新切分过 chunk）时自动作废，避免张冠李戴。"""
    if not config.CKPT_PATH.exists():
        return np.zeros((len(rowids), dim), np.float32), np.zeros(len(rowids), bool)
    try:
        z = np.load(config.CKPT_PATH)
        if z["rowids"].shape == rowids.shape and (z["rowids"] == rowids).all() and z["vecs"].shape[1] == dim:
            done = z["done"]
            print(f"↻ 载入检查点：已完成 {int(done.sum())}/{len(rowids)} 段")
            return z["vecs"].astype(np.float32), done
        print("⚠ 检查点与当前语料不匹配（chunk 或维度变了），忽略并重新开始")
    except Exception as e:  # noqa: BLE001
        print(f"⚠ 检查点损坏（{e}），忽略")
    return np.zeros((len(rowids), dim), np.float32), np.zeros(len(rowids), bool)


def save_ckpt(vecs, done, rowids):
    """先写临时文件再原子替换 —— 否则保存中途被打断会留下半个损坏的检查点。"""
    tmp = config.CKPT_PATH.with_suffix(".tmp.npz")
    np.savez(tmp, vecs=vecs, done=done, rowids=rowids)
    os.replace(tmp, config.CKPT_PATH)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=1, help="并发线程数，建议 1-4，太高会触发限流")
    ap.add_argument("--limit", type=int, default=None, help="只处理前 N 段，用于试水")
    ap.add_argument("--restart", action="store_true", help="丢弃检查点重来")
    ap.add_argument("--ckpt-every", type=int, default=20, help="每 N 个批次存一次检查点")
    ap.add_argument("--incremental", action="store_true",
                    help="复用已有 vectors.npy，只向量化新增段落（补索引后用这个）")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if a.restart and config.CKPT_PATH.exists():
        config.CKPT_PATH.unlink()
        print("已清除检查点")

    rowids, texts = load_chunks(a.limit)
    n, dim = len(rowids), config.EMBED_DIM
    chars = sum(len(t) for t in texts)
    print(f"待处理 {n} 段 / {chars:,} 字符，模型={config.EMBED_MODEL} 维度={dim}")
    print(f"预估 ≈{chars / 4 / 1000 * 0.0005:.2f} 元（按 4 字符/token、¥0.0005/千 token 粗算）")
    if a.dry_run:
        return 0
    if not config.DASHSCOPE_API_KEY:
        print("✗ 未配置 DASHSCOPE_API_KEY，请在 .env 里填好再跑")
        return 1

    vecs, done = load_ckpt(rowids, dim)
    if a.restart:
        vecs, done = np.zeros((n, dim), np.float32), np.zeros(n, bool)

    # 增量：把上一版 vectors.npy 里仍然有效的行搬过来，只算新增的
    if a.incremental and config.VEC_PATH.exists() and config.VEC_META_PATH.exists():
        old_v = np.load(config.VEC_PATH)
        old_meta = json.loads(config.VEC_META_PATH.read_text(encoding="utf-8"))
        old_map = {int(r): i for i, r in enumerate(old_meta["rowids"])}
        if old_v.shape[1] != dim:
            print(f"⚠ 旧向量维度 {old_v.shape[1]} ≠ 当前 {dim}，忽略增量，全部重算")
        else:
            reused = 0
            for i, rid in enumerate(rowids):
                j = old_map.get(int(rid))
                # 已被检查点算过的不覆盖；旧向量若是零向量（当初没跑完）也不复用
                if j is not None and not done[i] and np.any(old_v[j]):
                    vecs[i], done[i] = old_v[j], True
                    reused += 1
            print(f"↻ 增量模式：复用旧向量 {reused} 段，需新算 {n - reused} 段")

    todo = [i for i in range(n) if not done[i]]
    if not todo:
        print("全部已完成，直接导出")
    batches = [todo[i: i + config.EMBED_BATCH] for i in range(0, len(todo), config.EMBED_BATCH)]
    print(f"剩余 {len(todo)} 段，分 {len(batches)} 批（每批 ≤{config.EMBED_BATCH} 条，接口硬上限）")

    lock = threading.Lock()
    state = {"ok": 0, "fail": 0, "since_ckpt": 0}
    t0 = time.time()

    def run(bi_batch):
        bi, idxs = bi_batch
        try:
            out = embed_batch([texts[i] for i in idxs], text_type="document")
        except Exception as e:  # noqa: BLE001 — 单批失败不中断整体，最后统一报告
            with lock:
                state["fail"] += len(idxs)
                print(f"\n  ✗ 批 {bi} 失败：{e}")
            return
        with lock:
            for j, i in enumerate(idxs):
                vecs[i] = out[j]
                done[i] = True
            state["ok"] += len(idxs)
            state["since_ckpt"] += 1
            if state["since_ckpt"] >= a.ckpt_every:
                save_ckpt(vecs, done, rowids)
                state["since_ckpt"] = 0
            d = int(done.sum())
            el = time.time() - t0
            rate = state["ok"] / el if el > 0 else 0
            eta = (len(todo) - state["ok"]) / rate if rate > 0 else 0
            print(f"\r  {d}/{n}  ({d / n * 100:5.1f}%)  {rate:5.1f} 段/秒  剩余 ~{eta / 60:4.1f} 分  失败 {state['fail']}",
                  end="", flush=True)

    try:
        if a.workers > 1:
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=a.workers) as ex:
                list(ex.map(run, enumerate(batches)))
        else:
            for item in enumerate(batches):
                run(item)
    except KeyboardInterrupt:
        save_ckpt(vecs, done, rowids)
        print(f"\n\n已中断，进度存入 {config.CKPT_PATH}。重跑本脚本即可续传。")
        return 130

    save_ckpt(vecs, done, rowids)
    print()

    miss = int((~done).sum())
    if miss:
        print(f"⚠ 仍有 {miss} 段未完成（多为限流或网络抖动）。再跑一次本脚本会自动续传。")
        print("  未完成的段暂以零向量占位，不会被检索命中，不影响先跑通全流程。")

    # 保险起见再归一化一次：零向量占位行会被安全处理成零向量
    vecs = l2_normalize(vecs)
    np.save(config.VEC_PATH, vecs)
    config.VEC_META_PATH.write_text(json.dumps({
        "rowids": rowids.tolist(),
        "model": config.EMBED_MODEL,
        "dim": dim,
        "count": n,
        "completed": int(done.sum()),
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "normalized": True,
        "text_type": "document",
    }, ensure_ascii=False), encoding="utf-8")

    size = config.VEC_PATH.stat().st_size / 1e6
    print(f"✓ 已写出 {config.VEC_PATH}  {vecs.shape}  {size:.1f} MB")
    print(f"✓ 已写出 {config.VEC_META_PATH}")
    if not miss:
        print("  全部完成，检查点可以删了：data/.vectors_ckpt.npz")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
