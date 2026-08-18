#!/usr/bin/env python3
"""生成评测集骨架：20 道题 + 自动提名的「标准答案论文」，供人工校对。

我不知道每道题的真实标准答案 —— 那需要领域判断。所以这个脚本做的是：
用宽松的关键词检索给每道题提名候选论文，写进 data/eval_set.json 的
`gold_candidates`，你逐条看一眼，把真正相关的挪进 `gold`。

校对时的判据：这篇论文里**确实有能回答该问题的内容**，而不是"沾点边"。
宁可 gold 只留 2-3 篇最硬的，也别为了凑数放宽 —— 评测集的价值全在标注质量。

用法：
    python scripts/make_eval.py            # 生成骨架
    python scripts/make_eval.py --refresh  # 保留已校对的 gold，只刷新候选
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.retrieval import Index  # noqa: E402

EVAL_PATH = config.DATA_DIR / "eval_set.json"

# 五类题型，覆盖不同的检索失败模式：
#   numeric  数值型 —— 考验能否召回含具体实验数据的段落
#   mechanism机理型 —— 考验概念检索，关键词往往不字面出现
#   compare  对比型 —— 需要同时召回两个技术路线的论文
#   zh2en    中文检英文 —— 关键词路必然零召回，纯粹考验向量路
#   history  沿革型 —— 需要跨年代召回同一课题组的多篇论文
QUESTIONS = [
    # ---- 数值型 ----
    ("numeric", "film_motor", "静电薄膜电机的推力密度典型值范围是多少？", "thrust force density electrostatic film actuator N/cm2 kN/m2"),
    ("numeric", "film_motor", "静电薄膜驱动器的驱动电压通常是什么量级？", "driving voltage kV electrostatic film actuator applied voltage amplitude"),
    ("numeric", "electroadhesion", "electroadhesive clutch 能达到的剪切强度是多少？", "electroadhesive clutch shear stress holding force kPa"),
    ("numeric", "electroadhesion", "电粘附夹持器的吸附力与电压的定量关系？", "electroadhesion force voltage quadratic relationship normal force measurement"),
    # ---- 机理型 ----
    ("mechanism", "film_motor", "电极节距和间距如何影响静电薄膜电机的输出推力？", "electrode pitch gap spacing influence thrust output force"),
    ("mechanism", "film_motor", "绝缘液体对静电薄膜驱动器的推力有什么影响？", "insulating liquid dielectric fluid immersion thrust force enhancement"),
    ("mechanism", "film_motor", "击穿电压与电极间距的关系，Paschen 定律在这里如何适用？", "breakdown voltage electrode gap Paschen law air breakdown limit"),
    ("mechanism", "electroadhesion", "Johnsen-Rahbek 效应在静电吸附中起什么作用？", "Johnsen-Rahbek effect electrostatic chuck semiconductive interface"),
    ("mechanism", "electroadhesion", "表面粗糙度如何影响电粘附力？", "surface roughness contact interface electroadhesion force asperity"),
    ("mechanism", "film_motor", "驻极体在静电电机中如何提供偏置电荷？", "electret charge bias surface potential electrostatic motor low voltage"),
    # ---- 对比型 ----
    ("compare", "film_motor", "感应式静电电机和同步式静电电机在原理和效率上有何差异？", "induction type synchronous electrostatic motor comparison efficiency"),
    ("compare", "film_motor", "双激励（dual excitation）方案相比单激励有什么优势？", "dual excitation multiphase electrostatic drive advantage single excitation"),
    ("compare", "film_motor", "多层薄膜驱动器与单层结构相比推力提升多少？", "multi-layer multilayered electrostatic film actuator stacked thrust improvement"),
    ("compare", "electroadhesion", "电粘附夹持与气动夹持在软体机器人上各有什么优劣？", "electroadhesion versus pneumatic gripper soft robotics comparison"),
    # ---- 中文检英文（关键词路必然零召回，纯考验向量路）----
    ("zh2en", None, "静电吸附技术在爬壁机器人上是怎么应用的？", None),
    ("zh2en", None, "柔性静电驱动器的响应速度受什么限制？", None),
    ("zh2en", None, "静电离合器在可穿戴触觉设备里的作用是什么？", None),
    ("zh2en", None, "薄膜电机的滑块位置怎么做自感知？", None),
    # ---- 沿革型 ----
    ("history", "film_motor", "Higuchi 课题组的静电薄膜电机方案是怎么一步步演进的？", "Higuchi Niino Yamamoto electrostatic film motor development evolution"),
    ("history", "electroadhesion", "电粘附技术近十年在软体机器人领域的发展脉络？", "electroadhesion soft robotics development recent advances review"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="保留已校对的 gold，只刷新候选")
    ap.add_argument("--n", type=int, default=8, help="每题提名多少候选")
    a = ap.parse_args()

    old = {}
    if EVAL_PATH.exists():
        old = {q["id"]: q for q in json.loads(EVAL_PATH.read_text(encoding="utf-8"))["questions"]}
        print(f"已有评测集，保留其中已校对的 gold（{sum(1 for q in old.values() if q.get('gold'))} 题）")

    idx = Index()
    out = []
    for i, (kind, cat, q, probe) in enumerate(QUESTIONS, 1):
        qid = f"q{i:02d}"
        # 用 probe（英文关键词）而非问题本身来提名候选 —— 提名阶段要的是高召回，
        # 不能用待评测的那套检索逻辑，否则等于自己给自己打分
        hits = idx.keyword_search(probe or q, k=40, category=None)
        seen, cand = set(), []
        for rid in hits:
            h = idx._hydrate([rid], probe or q)
            if not h:
                continue
            f = h[0].file
            if f in seen:
                continue
            seen.add(f)
            cand.append({"file": f, "title": h[0].title[:90], "year": h[0].year,
                         "category": h[0].category, "tier": h[0].tier})
            if len(cand) >= a.n:
                break
        prev = old.get(qid, {})
        out.append({
            "id": qid,
            "type": kind,
            "category": cat,
            "question": q,
            "note": prev.get("note", ""),
            # ★ 你要填的就是这个：从 gold_candidates 里挑真正能回答该问题的，复制文件名进来
            "gold": prev.get("gold", []),
            "gold_candidates": cand if (not a.refresh or not prev.get("gold")) else prev.get("gold_candidates", cand),
        })
        print(f"  {qid} [{kind:9}] 提名 {len(cand):>2} 篇  {q[:38]}")

    EVAL_PATH.write_text(json.dumps({
        "version": 1,
        "note": "gold 需人工校对：从 gold_candidates 里挑出真正能回答该问题的论文文件名，填进 gold 数组。"
                "zh2en 类的候选多半为空（中文关键词检索不到英文文献），需要你手工指定。",
        "questions": out,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    todo = sum(1 for q in out if not q["gold"])
    print(f"\n✓ 已写出 {EVAL_PATH}")
    print(f"  待校对 {todo}/{len(out)} 题 —— 打开该文件，把 gold_candidates 里对的挪进 gold")
    print(f"  校对完跑：python scripts/eval.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
