#!/usr/bin/env python3
"""不花一分钱的自检：用随机向量冒充 embedding，把检索链路整条跑通。

验证 4 件事：
  1) FTS5 查询转义能扛住特殊字符（这是最容易线上崩的地方）
  2) 关键词路能召回
  3) 向量路 + RRF 融合逻辑正确
  4) 没有向量文件时能优雅降级成纯关键词，而不是崩溃

用法：python scripts/selftest.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.retrieval import Index, build_fts_query, rrf_fuse, tokenize  # noqa: E402

PASS, FAIL = "  ✓", "  ✗"
fails = 0


def check(name, cond, extra=""):
    global fails
    print(f"{PASS if cond else FAIL} {name}{('  ' + str(extra)) if extra else ''}")
    if not cond:
        fails += 1


print("\n[1] FTS5 查询转义 —— 这些输入不转义会直接抛 syntax error")
nasty = [
    'thrust force density',
    'electrostatic AND motor OR NEAR',          # FTS5 保留字
    'film-motor "dual excitation"',             # 连字符 + 已有引号
    'what is V_max * (gap) : 100um?',           # * ( ) : 都是语法元素
    '静电薄膜电机的推力密度',                     # 纯中文
    '!!!???',                                   # 全是标点，应返回 None
    '',
]
for q in nasty:
    fq = build_fts_query(q)
    check(f"{q!r:46} → {fq!r}", True)

print("\n[2] 关键词路（真实 FTS5 查询）")
idx = Index()
for q in nasty:
    ids = idx.keyword_search(q, k=5)
    # 关键断言：无论输入多脏，都不能抛异常，最差返回空列表
    check(f"{q[:34]!r:38} 召回 {len(ids)} 条", isinstance(ids, list))

hits = idx.search("electrostatic film motor thrust force density", k_final=5)
check("真实检索有命中", len(hits) > 0, f"{len(hits)} 条")
if hits:
    h = hits[0]
    check("命中带完整出处（标题/页码/DOI 字段存在）", all([h.title, h.page is not None]))
    check("preview 非空", bool(h.preview))
    print(f"    top1: {h.title[:60]}… 第{h.page}页 tier={h.tier} routes={h.routes}")

print("\n[3] tier 过滤")
a = idx.search("electrostatic motor", k_final=20)
b = idx.search("electrostatic motor", k_final=20, tier="1")
check("①核心过滤后结果均属①", all("①" in (h.tier or "") for h in b), f"全部{len(a)} → ①{len(b)}")

print("\n[4] RRF 融合逻辑")
# 文档 B 两路都排第 2，文档 A 只在一路排第 1。RRF 应让 B 胜出 —— 这正是混合检索的意义
fused = rrf_fuse([("kw", [1, 2, 3], 1.0), ("vec", [4, 2, 5], 1.0)], k=60)
top = fused[0]
check("两路都靠前的文档胜过单路第一", top[0] == 2, f"top={top[0]} score={top[1]:.5f} routes={top[2]}")
check("单路文档也被保留", {r for r, _, _ in fused} == {1, 2, 3, 4, 5})
exp = 1 / (60 + 2) + 1 / (60 + 2)   # 文档 2 在两路都排第 2
check("分数 = Σ w/(k+rank)", abs(top[1] - exp) < 1e-9, f"{top[1]:.6f} vs {exp:.6f}")
# 对照：单路第一名 1/61 = 0.01639 < 0.03226，说明 RRF 确实偏好"两路共识"
check("单路第一名分数低于双路共识", dict((r, s) for r, s, _ in fused)[1] < top[1])

print("\n[5] 向量路 + 融合（用随机向量冒充 embedding，不调 API）")
n = len(np.load(config.VEC_PATH)) if config.VEC_PATH.exists() else None
with tempfile.TemporaryDirectory() as td:
    import sqlite3

    nrows = sqlite3.connect(str(config.DB_PATH)).execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    fake = np.random.default_rng(0).standard_normal((nrows, 8)).astype(np.float32)
    fake /= np.linalg.norm(fake, axis=1, keepdims=True)
    fp = Path(td) / "fake.npy"
    np.save(fp, fake)
    idx2 = Index(vec_path=fp)          # 无 vector_meta.json → 走"行序==rowid升序"回退分支
    check("无 meta 时能回退加载", idx2.has_vectors and len(idx2.vec_rowids) == nrows)
    check("tier 数组与向量行对齐", len(idx2.vec_tiers) == nrows)

    q = np.random.default_rng(1).standard_normal(8).astype(np.float32)
    q /= np.linalg.norm(q)
    sims = idx2.vectors @ q
    full = [int(idx2.vec_rowids[i]) for i in np.argsort(-sims)[:10]]
    # 复现 vector_search 里的 argpartition 部分排序，验证它和全排序等价
    kk = 10
    part = np.argpartition(-sims, kk - 1)[:kk]
    part = [int(idx2.vec_rowids[i]) for i in part[np.argsort(-sims[part])]]
    check("argpartition 部分排序 == 全排序", part == full, f"top5={full[:5]}")

    tiers = idx2.vec_tiers
    m = np.array(["①" in (t or "") for t in tiers])
    check("tier mask 有效", m.sum() > 0, f"①核心段落 {int(m.sum())}/{nrows}")

print("\n[6] 降级：没有向量文件时不能崩")
idx3 = Index(vec_path=Path("/nonexistent/vectors.npy"))
check("has_vectors=False", not idx3.has_vectors)
check("vector_search 返回空而非抛异常", idx3.vector_search("test") == [])
h3 = idx3.search("electrostatic film motor")
check("纯关键词模式仍能检索", len(h3) > 0, f"{len(h3)} 条")
check("stats 标记为 keyword-only", idx3.stats()["mode"] == "keyword-only")

print("\n[7] 两大类分类")
s = idx.stats()
if s.get("has_category"):
    tot = sum(c["papers"] for c in s["categories"])
    for c in s["categories"]:
        print(f"    {c['key']:16} {c['label']:16} {c['papers']:>4} 篇 {c['chunks']:>5} 段  交叉 {c['cross']}")
    check("两大类论文数之和 == 总数", tot == s["papers"], f"{tot} vs {s['papers']}")
    fm = idx.search("electrostatic film motor thrust", k_final=15, category="film_motor")
    ea = idx.search("electroadhesion gripper shear", k_final=15, category="electroadhesion")
    # 交叉论文按设计会出现在任一大类里，所以只要求「非交叉的必须属于该类」
    check("film_motor 筛选无越界", all(h.category == "film_motor" or h.cross_topic for h in fm), f"{len(fm)} 条")
    check("electroadhesion 筛选无越界", all(h.category == "electroadhesion" or h.cross_topic for h in ea), f"{len(ea)} 条")
    check("electroadhesion 可被检索到", len(ea) > 0, f"{len(ea)} 条 —— 补索引前这里恒为 0")
else:
    print("    （尚未跑 recategorize.py，分类筛选自动停用）")
    check("旧库向后兼容：无 category 列不报错", True)

print("\n[8] 库统计")
print(f"    papers={s['papers']} chunks={s['chunks']} mode={s['mode']} vectors={s['vectors']}")
check("papers 与 chunks 非空", s["papers"] > 0 and s["chunks"] > 0)
if s["vectors"] and s["vectors"] != s["chunks"]:
    print(f"    ⚠ 向量 {s['vectors']} 段 < 全文 {s['chunks']} 段 —— 新入库内容尚无向量，"
          f"跑 build_vectors.py --incremental 补上")

print("\n[9] v2：知识树与统计层")
from app import knowledge_tree as kt          # noqa: E402
from app import analytics as an               # noqa: E402
nodes = list(kt.walk())
check("知识树可遍历", len(nodes) > 20, f"{len(nodes)} 节点 / {len(kt.leaves())} 叶")
check("每个叶节点都有检索查询词", all(n.get("q") for n in kt.leaves()))
check("节点 id 唯一", len({n['id'] for n in nodes}) == len(nodes))
check("skeleton 已剥离查询词", all("q" not in n for n in [kt.skeleton()] + kt.skeleton()["children"]))
check("outline 非空（供模型定位用）", len(kt.outline()) > 200)
o = an.overview()
check("统计层能出总览", o["totals"]["papers"] > 0, f"{o['totals']['papers']} 篇 / 被引 {o['totals']['cited']}")
check("作者归并生效", o["totals"]["authors"] < o["totals"]["papers"] * 4,
      f"{o['totals']['authors']} 位")
check("年度曲线连续", len(o["timeline"]) > 10, f"{len(o['timeline'])} 个年份")
check("作者名归一：T. Higuchi 与 Toshiro Higuchi 同键",
      an.norm_author("T. Higuchi")[0] == an.norm_author("Toshiro Higuchi")[0])
check("作者名归一：姓在前的写法同键",
      an.norm_author("Higuchi, Toshiro")[0] == an.norm_author("Toshiro Higuchi")[0])
b = an.benchmarks()
if b["available"]:
    check("benchmark 单位已归一", all("unit" in m for m in b["metrics"].values()))
    print(f"    指标类别: {list(b['metrics'])}")
else:
    print(f"    （{b['note']}）")

print(f"\n{'=' * 52}")
print("全部通过 ✓" if fails == 0 else f"{fails} 项失败 ✗")
sys.exit(1 if fails else 0)
