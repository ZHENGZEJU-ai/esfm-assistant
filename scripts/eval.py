#!/usr/bin/env python3
"""评测检索质量。这是之后所有调参的唯一依据 —— 没有它，改参数就只是凭感觉。

指标（都在**论文级**上算，不是段落级 —— 同一篇论文的多个段落命中只算一次）：
  Recall@k  gold 论文有多少比例出现在前 k 条里。最重要的指标：召不回就无从回答。
  MRR       第一篇 gold 论文的排名倒数。反映"用户要不要往下翻"。
  nDCG@k    考虑排序位置的综合分。

用法：
    python scripts/eval.py                      # 评当前配置
    python scripts/eval.py --compare            # 关键词路 / 向量路 / 混合 三者对比
    python scripts/eval.py --sweep-weights      # 扫 RRF 两路权重
    python scripts/eval.py --no-expand          # 关掉中译英扩写，看它到底值不值
    python scripts/eval.py --k 20               # 改 k
    python scripts/eval.py --verbose            # 打印每题细节，看是哪些题拖后腿
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.retrieval import Index, rrf_fuse  # noqa: E402

EVAL_PATH = config.DATA_DIR / "eval_set.json"


def dcg(rels: list[int]) -> float:
    return sum(r / math.log2(i + 2) for i, r in enumerate(rels))


def score_one(ranked_files: list[str], gold: list[str], k: int) -> dict:
    """ranked_files 是去重后的论文级排序结果。"""
    top = ranked_files[:k]
    gset = set(gold)
    hit = [1 if f in gset else 0 for f in top]
    recall = sum(hit) / len(gset) if gset else 0.0
    mrr = 0.0
    for i, f in enumerate(top, 1):
        if f in gset:
            mrr = 1 / i
            break
    ideal = dcg([1] * min(len(gset), k))
    return {"recall": recall, "mrr": mrr,
            "ndcg": (dcg(hit) / ideal) if ideal else 0.0,
            "hits": sum(hit), "n_gold": len(gset)}


def to_papers(hits) -> list[str]:
    """段落级结果 → 论文级去重排序。"""
    out, seen = [], set()
    for h in hits:
        if h.file not in seen:
            seen.add(h.file)
            out.append(h.file)
    return out


def run(idx: Index, q: dict, mode: str, k: int, expand: bool,
        wk: float, wv: float) -> list[str]:
    from app import llm

    query = q["question"]
    if expand:
        try:
            query = llm.expand_query(query)
        except Exception:  # noqa: BLE001
            pass
    cat = q.get("category")
    if mode == "keyword":
        ids = idx.keyword_search(query, k * 4, None, cat)
    elif mode == "vector":
        ids = idx.vector_search(query, k * 4, None, cat)
    else:
        kw = idx.keyword_search(query, config.K_KEYWORD, None, cat)
        vec = idx.vector_search(query, config.K_VECTOR, None, cat)
        ids = [r for r, _, _ in rrf_fuse([("keyword", kw, wk), ("vector", vec, wv)])]
    return to_papers(idx._hydrate(ids[: k * 4], query))[: k * 4]


def evaluate(idx, qs, mode, k, expand, wk=config.W_KEYWORD, wv=config.W_VECTOR, verbose=False):
    agg, by_type = defaultdict(list), defaultdict(lambda: defaultdict(list))
    for q in qs:
        files = run(idx, q, mode, k, expand, wk, wv)
        s = score_one(files, q["gold"], k)
        for m in ("recall", "mrr", "ndcg"):
            agg[m].append(s[m])
            by_type[q["type"]][m].append(s[m])
        if verbose:
            flag = "✓" if s["recall"] >= 0.5 else ("△" if s["recall"] > 0 else "✗")
            print(f"    {flag} {q['id']} [{q['type']:9}] R={s['recall']:.2f} "
                  f"MRR={s['mrr']:.2f} ({s['hits']}/{s['n_gold']}) {q['question'][:32]}")
    mean = {m: (sum(v) / len(v) if v else 0.0) for m, v in agg.items()}
    return mean, {t: {m: sum(v) / len(v) for m, v in d.items()} for t, d in by_type.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--sweep-weights", action="store_true")
    ap.add_argument("--no-expand", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    a = ap.parse_args()

    if not EVAL_PATH.exists():
        print(f"✗ 没有 {EVAL_PATH}，先跑 python scripts/make_eval.py")
        return 1
    data = json.loads(EVAL_PATH.read_text(encoding="utf-8"))
    qs = [q for q in data["questions"] if q.get("gold")]
    skipped = len(data["questions"]) - len(qs)
    if not qs:
        print("✗ 评测集里没有一道题标了 gold。")
        print("  打开 data/eval_set.json，把每题 gold_candidates 里真正能回答该问题的")
        print("  论文文件名挪进 gold 数组，再回来跑。")
        return 1
    print(f"评测集：{len(qs)} 题可用" + (f"（{skipped} 题未标注 gold，已跳过）" if skipped else ""))
    print(f"配置：k={a.k} expand={'off' if a.no_expand else 'on'} "
          f"检索模式={'hybrid' if idx_has_vec else 'keyword-only'}\n")

    expand = not a.no_expand

    if a.compare:
        print(f"{'模式':<12}{'Recall@k':>10}{'MRR':>8}{'nDCG':>8}")
        print("-" * 38)
        rows = {}
        for mode in ("keyword", "vector", "hybrid"):
            m, _ = evaluate(idx, qs, mode, a.k, expand)
            rows[mode] = m
            print(f"{mode:<12}{m['recall']:>10.3f}{m['mrr']:>8.3f}{m['ndcg']:>8.3f}")
        best_single = max(rows['keyword']['recall'], rows['vector']['recall'])
        gain = rows['hybrid']['recall'] - best_single
        print(f"\n混合相对最优单路的 Recall 增益：{gain:+.3f}")
        if gain <= 0:
            print("  ⚠ 混合没有跑赢单路 —— 检查是不是某一路基本没召回（gold 标注太少也会这样）")
        return 0

    if a.sweep_weights:
        print(f"{'W_kw':>6}{'W_vec':>7}{'Recall':>9}{'MRR':>8}{'nDCG':>8}")
        print("-" * 38)
        best = None
        for wk, wv in [(1, 0), (2, 1), (1.5, 1), (1, 1), (1, 1.5), (1, 2), (0, 1)]:
            m, _ = evaluate(idx, qs, "hybrid", a.k, expand, wk, wv)
            print(f"{wk:>6}{wv:>7}{m['recall']:>9.3f}{m['mrr']:>8.3f}{m['ndcg']:>8.3f}")
            if best is None or m["ndcg"] > best[0]:
                best = (m["ndcg"], wk, wv)
        print(f"\n最优：W_KEYWORD={best[1]} W_VECTOR={best[2]}（nDCG={best[0]:.3f}）")
        print("  改 app/config.py 里的 W_KEYWORD / W_VECTOR 生效")
        return 0

    mean, by_type = evaluate(idx, qs, "hybrid", a.k, expand, verbose=a.verbose)
    print(f"总体  Recall@{a.k}={mean['recall']:.3f}  MRR={mean['mrr']:.3f}  nDCG={mean['ndcg']:.3f}\n")
    print(f"{'题型':<12}{'Recall':>9}{'MRR':>8}{'nDCG':>8}")
    print("-" * 37)
    for t, m in sorted(by_type.items()):
        print(f"{t:<12}{m['recall']:>9.3f}{m['mrr']:>8.3f}{m['ndcg']:>8.3f}")
    print("\n看哪一类分低就往哪里调：")
    print("  zh2en 低    → 向量路或查询扩写有问题，先跑 --no-expand 对比")
    print("  numeric 低  → chunk 太粗，含数据的段落被稀释；调小 ingest_pdfs.py 的 TARGET")
    print("  compare 低  → K_FINAL 太小，装不下两条技术路线；调大试试")
    print("  history 低  → 需要按年份/被引加权，或加 rerank")
    return 0


idx = Index()
idx_has_vec = idx.has_vectors

if __name__ == "__main__":
    raise SystemExit(main())
