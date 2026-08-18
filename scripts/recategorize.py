#!/usr/bin/env python3
"""把文献重新归入 film_motor / electroadhesion 两大类，并重组 PDFs 目录。

判定策略（三票制）：
  票源 1  PDF 所在文件夹        00/01 → FM   02 → EA   03 → 交叉
  票源 2  catalog_all「方向」    静电薄膜驱动器 → FM   电粘附 → EA   两者交叉 → 交叉
  票源 3  catalog_film「分级」   ①② → FM      ③ → EA
三票一致直接采纳；出现冲突或无票源时，交给大模型读标题+摘要判定。
已知的一类冲突：6 篇标题明写 electroadhesion 的论文被放在 film_motor 文件夹里，
但「分级」列标的是 ③ —— 文件夹错、分级对，模型复核会纠正过来。

用法：
    python scripts/recategorize.py --dry-run       # 只看结果，不落盘
    python scripts/recategorize.py --no-llm        # 冲突件按「分级」列裁决，不调模型
    python scripts/recategorize.py                 # 写入数据库
    python scripts/recategorize.py --move-files    # 同时把 PDF 物理重组成两个文件夹
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402

FM, EA = "film_motor", "electroadhesion"
LABEL = {FM: "静电薄膜电机", EA: "静电吸附/电粘附"}
PDF_ROOT = config.ROOT / "PDFs"

FOLDER_VOTE = {
    "00_film_motor_focus": FM,
    "01_electrostatic_film_actuators": FM,
    "02_electroadhesion": EA,
    "03_both_overlap": "CROSS",
}
DIR_VOTE = {"静电薄膜驱动器": FM, "电粘附": EA, "两者交叉": "CROSS"}


def load_catalogs() -> dict:
    import openpyxl

    meta: dict[str, dict] = {}
    for path, pathcol, catcol, key in [
        (config.DATA_DIR / "catalog_all.xlsx", "本地文件路径", "方向", "direction"),
        (config.DATA_DIR / "catalog_film_motor.xlsx", "本地路径", "分级", "tier"),
    ]:
        if not path.exists():
            continue
        ws = openpyxl.load_workbook(path, read_only=True).worksheets[0]
        rows = ws.iter_rows(values_only=True)
        hdr = list(next(rows))
        ip, ic, it = hdr.index(pathcol), hdr.index(catcol), hdr.index("标题")
        iab = hdr.index("摘要") if "摘要" in hdr else None
        for r in rows:
            if not r[ip]:
                continue
            base = os.path.basename(str(r[ip]).replace("\\", "/"))
            if not base.endswith(".pdf"):
                base += ".pdf"
            d = meta.setdefault(base, {})
            d[key] = r[ic]
            d.setdefault("title", r[it])
            if iab is not None and r[iab] and not d.get("abstract"):
                d["abstract"] = r[iab]
    return meta


def vote(fname: str, folder: str, m: dict) -> tuple[list[str], list[str]]:
    votes, basis = [], []
    if (v := FOLDER_VOTE.get(folder)):
        votes.append(v)
        basis.append(f"folder={folder}")
    if (d := m.get("direction")) and (v := DIR_VOTE.get(str(d).strip())):
        votes.append(v)
        basis.append(f"方向={d}")
    t = str(m.get("tier") or "")
    if t.startswith("③"):
        votes.append(EA)
        basis.append(f"分级={t.strip()}")
    elif t.startswith(("①", "②")):
        votes.append(FM)
        basis.append(f"分级={t.strip()}")
    return votes, basis


LLM_SYS = """你是静电驱动领域的文献分类器。把论文归入下面两类之一：

film_motor —— 静电薄膜电机 / 静电薄膜驱动器 / 静电马达。特征：靠电极阵列的行波或
步进电场驱动滑块或薄膜产生**相对运动**，关注推力、速度、效率、多相激励、电介质极化。

electroadhesion —— 静电吸附 / 电粘附 / 静电夹持 / 电致离合。特征：靠静电力产生
**法向吸附或剪切握持**，关注吸附力、剪切强度、剥离力、夹持器、爬壁、离合器、触觉显示。

只输出一行 JSON，不要任何解释：
{"category":"film_motor 或 electroadhesion","cross":true 或 false,"reason":"12字以内"}
cross 表示论文同时实质涉及两个方向（只是提了一句不算）。"""


def llm_judge(items: list[dict]) -> dict:
    from app import llm

    out = {}
    for i, it in enumerate(items, 1):
        q = f"标题：{it['title']}\n摘要：{(it.get('abstract') or '')[:900]}"
        try:
            raw = llm.chat([{"role": "system", "content": LLM_SYS},
                            {"role": "user", "content": q}], temperature=0.0, max_tokens=120)
            js = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
            if js.get("category") in (FM, EA):
                out[it["file"]] = js
                print(f"    [{i}/{len(items)}] {js['category']:16} cross={str(js.get('cross')):5} "
                      f"{js.get('reason', '')[:14]:16} {it['file'][:40]}")
                continue
        except Exception as e:  # noqa: BLE001
            print(f"    [{i}/{len(items)}] ✗ 判定失败({type(e).__name__})，回退元数据 {it['file'][:40]}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-llm", action="store_true", help="冲突件按「分级」列裁决，不调模型")
    ap.add_argument("--move-files", action="store_true", help="同时物理重组 PDFs 目录")
    a = ap.parse_args()

    con = sqlite3.connect(str(config.DB_PATH))
    con.row_factory = sqlite3.Row
    papers = {r["file"]: dict(r) for r in con.execute("SELECT file,title,tier,abstract FROM papers")}
    meta = load_catalogs()

    folder = {}
    for d in sorted(PDF_ROOT.iterdir()):
        if d.is_dir():
            for f in d.glob("*.pdf"):
                folder.setdefault(f.name, d.name)

    all_files = sorted(set(papers) | set(folder))
    result, need_llm = {}, []
    for f in all_files:
        m = meta.get(f, {})
        if not m.get("title"):
            m["title"] = (papers.get(f) or {}).get("title") or f
        if not m.get("abstract"):
            m["abstract"] = (papers.get(f) or {}).get("abstract") or ""
        votes, basis = vote(f, folder.get(f, ""), m)
        clean = [v for v in votes if v != "CROSS"]
        cross = "CROSS" in votes
        if len(set(clean)) == 1:
            result[f] = {"category": clean[0], "cross": cross, "by": "metadata", "basis": basis}
        else:
            need_llm.append({"file": f, "title": m["title"], "abstract": m["abstract"],
                             "votes": votes, "basis": basis})

    print(f"文件总数 {len(all_files)}（库内 {len(papers)} · 磁盘 {len(folder)}）")
    print(f"  元数据一致直接判定: {len(result)}")
    print(f"  需复核（冲突/无票源）: {len(need_llm)}")
    for x in need_llm:
        print(f"      {'/'.join(x['basis']) or '无元数据':44} {x['title'][:48]}")

    if need_llm:
        if a.no_llm:
            print("\n  --no-llm：按「分级」列裁决（分级列比文件夹可靠）")
            for x in need_llm:
                t = str(meta.get(x["file"], {}).get("tier") or "")
                c = EA if t.startswith("③") else FM
                result[x["file"]] = {"category": c, "cross": True, "by": "tier-fallback",
                                     "basis": x["basis"]}
        else:
            print(f"\n  调用 {config.LLM_PROVIDER} 复核 {len(need_llm)} 篇（约 ¥{len(need_llm)*0.002:.3f}）：")
            judged = llm_judge(need_llm)
            for x in need_llm:
                j = judged.get(x["file"])
                if j:
                    result[x["file"]] = {"category": j["category"], "cross": bool(j.get("cross")),
                                         "by": "llm", "basis": x["basis"] + [f"llm:{j.get('reason','')}"]}
                else:
                    t = str(meta.get(x["file"], {}).get("tier") or "")
                    result[x["file"]] = {"category": EA if t.startswith("③") else FM,
                                         "cross": True, "by": "tier-fallback", "basis": x["basis"]}

    c = Counter(v["category"] for v in result.values())
    print(f"\n分类结果：")
    for k in (FM, EA):
        print(f"  {k:16} {LABEL[k]:14} {c[k]:>4} 篇")
    print(f"  其中标记为交叉      {sum(1 for v in result.values() if v['cross']):>4} 篇")
    print(f"  判定来源: {dict(Counter(v['by'] for v in result.values()))}")

    if a.dry_run:
        print("\n--dry-run，未落盘。")
        (config.DATA_DIR / "categories_preview.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"判定明细已写出供核对 → data/categories_preview.json")
        return 0

    # ---- 落库 ----
    shutil.copy2(config.DB_PATH, str(config.DB_PATH) + ".bak")
    cols = {r[1] for r in con.execute("PRAGMA table_info(papers)")}
    if "category" not in cols:
        con.execute("ALTER TABLE papers ADD COLUMN category TEXT")
    if "cross_topic" not in cols:
        con.execute("ALTER TABLE papers ADD COLUMN cross_topic INT DEFAULT 0")
    for f, v in result.items():
        if f in papers:
            con.execute("UPDATE papers SET category=?, cross_topic=? WHERE file=?",
                        (v["category"], int(v["cross"]), f))
    con.commit()
    (config.DATA_DIR / "categories.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    n = con.execute("SELECT category, COUNT(*) FROM papers GROUP BY category").fetchall()
    print(f"\n✓ 已写入数据库: {dict(n)}")

    # ---- 物理重组 ----
    if a.move_files:
        moved = 0
        for cat in (FM, EA):
            (PDF_ROOT / cat).mkdir(exist_ok=True)
        for f, src_dir in folder.items():
            v = result.get(f)
            if not v or src_dir in (FM, EA):
                continue
            src, dst = PDF_ROOT / src_dir / f, PDF_ROOT / v["category"] / f
            if src.exists() and not dst.exists():
                shutil.move(str(src), str(dst))
                moved += 1
        for d in list(PDF_ROOT.iterdir()):
            if d.is_dir() and d.name not in (FM, EA) and not any(d.iterdir()):
                d.rmdir()
        print(f"✓ 已移动 {moved} 个 PDF")
        for d in sorted(PDF_ROOT.iterdir()):
            if d.is_dir():
                print(f"    PDFs/{d.name}/  {len(list(d.glob('*.pdf')))} 篇")

    con.close()
    print("\n下一步：python scripts/build_vectors.py --incremental && 重启 uvicorn")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
