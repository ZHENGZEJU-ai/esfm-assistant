#!/usr/bin/env python3
"""清除 PDF 里被当成正文切进索引的出版商下载水印。

问题：IEEE Xplore 在每页页脚打了机构下载水印
    "Authorized licensed use limited to: <机构>. Downloaded on <日期> ... Restrictions apply."
切分时这些页脚被当成正文，产生两类脏数据：
    A. 196 段整段都是水印        → 直接删（连同它们的向量）
    B. 77 段水印夹在真正文里     → 剥离水印后重新向量化（只重算这 77 段，成本约 ¥0.02）

用法：
    python scripts/clean_boilerplate.py --dry-run   # 先看会改什么，不落盘（推荐）
    python scripts/clean_boilerplate.py             # 真正执行

会自动备份 data/library.db → data/library.db.bak，向量同理。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402

# 完整水印句。宽松匹配机构名和日期，末尾 "Restrictions apply." 是 IEEE 固定收尾。
WATERMARK = re.compile(
    r"Authorized licensed use limited to:.{0,120}?"
    r"Downloaded on .{0,80}?from IEEE Xplore\.\s*Restrictions apply\.",
    re.I | re.S,
)
# 兜底：上面匹配不到时，至少切掉从水印开头到行尾
WATERMARK_LOOSE = re.compile(r"Authorized licensed use limited to:.*?(?:\n|$)", re.I)

PURE_RATIO = 0.9   # 剥离后剩余内容不足原文 10% → 视为纯水印段，删除
MIN_KEEP = 120     # 剥离后短于这个长度也视为无检索价值


def strip_wm(t: str) -> str:
    out = WATERMARK.sub(" ", t or "")
    if "Authorized licensed use" in out:
        out = WATERMARK_LOOSE.sub(" ", out)
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect(str(config.DB_PATH))
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT rowid AS rid, file, page, text, title FROM chunks ORDER BY rowid").fetchall()

    drop, edit = [], []
    for r in rows:
        t = r["text"] or ""
        if "Authorized licensed use" not in t:
            continue
        s = strip_wm(t)
        if len(s) < MIN_KEEP or len(s) < len(t) * (1 - PURE_RATIO):
            drop.append(r["rid"])
        else:
            edit.append((r["rid"], s, len(t) - len(s)))

    print(f"扫描 {len(rows)} 段")
    print(f"  A 整段水印，将删除      : {len(drop)} 段")
    print(f"  B 水印夹在正文，将剥离  : {len(edit)} 段（剥离后需重新向量化，约 ¥{len(edit) * 0.0000005 * 1500:.3f}）")
    print(f"  清洗后剩余              : {len(rows) - len(drop)} 段")
    if edit:
        rid, s, cut = edit[0]
        print(f"\n  剥离样例 rowid={rid}：去掉 {cut} 字符水印，保留 {len(s)} 字符正文")
    if a.dry_run:
        print("\n--dry-run，未落盘。去掉该参数即真正执行。")
        return 0
    if not drop and not edit:
        print("\n没有需要清理的内容。")
        return 0

    # ---- 备份。删 FTS5 行是不可逆操作，必须先留退路 ----
    for p in (config.DB_PATH, config.VEC_PATH, config.VEC_META_PATH):
        if Path(p).exists():
            shutil.copy2(p, str(p) + ".bak")
    print(f"\n已备份 → {config.DB_PATH}.bak 等")

    # ---- 1. 剥离 B 类 ----
    for rid, s, _ in edit:
        con.execute("UPDATE chunks SET text = ? WHERE rowid = ?", (s, rid))
    # ---- 2. 删除 A 类 ----
    con.executemany("DELETE FROM chunks WHERE rowid = ?", [(r,) for r in drop])
    con.commit()

    # ---- 3. 同步向量：删掉 A 类的行，B 类重新向量化 ----
    if config.VEC_PATH.exists():
        v = np.load(config.VEC_PATH)
        meta = json.loads(config.VEC_META_PATH.read_text(encoding="utf-8"))
        rowids = np.asarray(meta["rowids"], dtype=np.int64)
        keep = ~np.isin(rowids, np.asarray(drop, dtype=np.int64))
        v, rowids = v[keep], rowids[keep]
        print(f"向量 {len(keep)} → {len(v)} 行")

        if edit:
            from app.embed import embed_batch

            pos = {int(r): i for i, r in enumerate(rowids)}
            todo = []
            for rid, s, _ in edit:
                if rid not in pos:
                    continue
                row = con.execute("SELECT title FROM chunks WHERE rowid = ?", (rid,)).fetchone()
                title = ((row["title"] if row else "") or "")[:200]
                # 与 build_vectors.py 保持完全一致的拼法，否则新旧向量不在同一语义空间
                todo.append((pos[rid], f"{title}\n\n{s}" if title else s))
            print(f"重新向量化 {len(todo)} 段…")
            for i in range(0, len(todo), config.EMBED_BATCH):
                b = todo[i: i + config.EMBED_BATCH]
                out = embed_batch([txt[: config.EMBED_MAX_CHARS] for _, txt in b], text_type="document")
                for j, (idx, _) in enumerate(b):
                    v[idx] = out[j]
                print(f"\r  {min(i + config.EMBED_BATCH, len(todo))}/{len(todo)}", end="", flush=True)
            print()

        np.save(config.VEC_PATH, v.astype(np.float32))
        meta.update({"rowids": rowids.tolist(), "count": len(rowids),
                     "completed": len(rowids), "cleaned": True})
        config.VEC_META_PATH.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    con.commit()
    con.isolation_level = None   # VACUUM 不能在事务里执行
    con.execute("VACUUM")
    con.close()
    n = con_count()
    print(f"\n✓ 完成。chunks {len(rows)} → {n}，向量已同步")
    print("  记得重启 uvicorn 让新索引生效")
    print("  确认无误后可删除 .bak 备份文件")
    return 0


def con_count() -> int:
    c = sqlite3.connect(str(config.DB_PATH))
    n = c.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    c.close()
    return n


if __name__ == "__main__":
    raise SystemExit(main())
