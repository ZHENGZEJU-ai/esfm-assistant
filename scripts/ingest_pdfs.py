#!/usr/bin/env python3
"""把磁盘上有、但没进全文索引的 PDF 补进 papers + chunks。

背景：285 篇 PDF 里只有 195 篇进了索引，78 篇 electroadhesion 全部在外 ——
也就是助手此前根本搜不到电粘附文献。这个脚本补齐这个缺口。

元数据（标题/作者/年份/期刊/DOI/被引/分级）从两份 catalog xlsx 里取，
正文按「页 → 段」切分，与既有 3547 段的粒度保持一致（目标 1200 字符）。

用法：
    python scripts/ingest_pdfs.py --dry-run    # 先看会入库什么
    python scripts/ingest_pdfs.py              # 执行（自动备份 db）
    python scripts/ingest_pdfs.py --force 文件名.pdf   # 单篇重新入库

入库后必须跑：python scripts/build_vectors.py --incremental
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402

TARGET = 1200   # 目标段长，与既有语料中位数(1198)对齐
MIN_CHUNK = 200  # 短于此的碎片并入上一段
PDF_ROOT = config.ROOT / "PDFs"

# 出版商水印，抽取阶段就地清掉，避免重蹈 clean_boilerplate 的覆辙
NOISE = [
    re.compile(r"Authorized licensed use limited to:.{0,120}?Restrictions apply\.", re.I | re.S),
    re.compile(r"Downloaded on .{0,60}?from IEEE Xplore\.", re.I),
    re.compile(r"This article has been accepted for publication.{0,160}?content may change", re.I | re.S),
]


def clean(t: str) -> str:
    for p in NOISE:
        t = p.sub(" ", t or "")
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def split_page(text: str) -> list[str]:
    """按段落边界切成接近 TARGET 的块，不做重叠（与既有语料一致）。"""
    text = clean(text)
    if len(text) <= TARGET * 1.4:
        return [text] if len(text) >= MIN_CHUNK else []
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paras:
        paras = [text]
    out, buf = [], ""
    for p in paras:
        # 单段就超长（常见于双栏 PDF 抽出的整页文本）→ 按句子再切
        while len(p) > TARGET * 1.6:
            cut = p.rfind(". ", 0, TARGET)
            cut = cut + 2 if cut > TARGET // 2 else TARGET
            head, p = p[:cut], p[cut:]
            if buf:
                out.append(buf.strip())
                buf = ""
            out.append(head.strip())
        if len(buf) + len(p) + 2 > TARGET and buf:
            out.append(buf.strip())
            buf = p
        else:
            buf = f"{buf}\n\n{p}" if buf else p
    if buf:
        out.append(buf.strip())
    # 合并过短的尾巴
    merged: list[str] = []
    for s in out:
        if merged and len(s) < MIN_CHUNK:
            merged[-1] += "\n\n" + s
        else:
            merged.append(s)
    return [s for s in merged if len(s) >= MIN_CHUNK // 2]


def load_catalog_meta() -> dict:
    """从两份 xlsx 取元数据，键为 PDF 文件名。catalog_film_motor 优先（字段更全）。"""
    try:
        import openpyxl
    except ImportError:
        print("需要 openpyxl：pip install openpyxl")
        raise
    meta: dict[str, dict] = {}
    specs = [
        (config.DATA_DIR / "catalog_all.xlsx", "本地文件路径", "方向"),
        (config.DATA_DIR / "catalog_film_motor.xlsx", "本地路径", "分级"),
    ]
    for path, pathcol, catcol in specs:
        if not path.exists():
            continue
        ws = openpyxl.load_workbook(path, read_only=True).worksheets[0]
        rows = ws.iter_rows(values_only=True)
        hdr = list(next(rows))

        def col(*names):
            for n in names:
                if n in hdr:
                    return hdr.index(n)
            return None

        ip, ic = hdr.index(pathcol), hdr.index(catcol)
        it = col("标题")
        ia, iy = col("作者"), col("年份")
        iv, idoi = col("期刊/来源", "期刊"), col("DOI")
        icit, iab = col("被引次数"), col("摘要")
        for r in rows:
            if not r[ip]:
                continue
            base = os.path.basename(str(r[ip]).replace("\\", "/"))
            if not base.endswith(".pdf"):
                base += ".pdf"
            d = meta.setdefault(base, {})
            def put(k, i):
                if i is not None and r[i] not in (None, "") and not d.get(k):
                    d[k] = r[i]
            put("title", it); put("authors", ia); put("year", iy)
            put("venue", iv); put("doi", idoi); put("cited", icit); put("abstract", iab)
            d.setdefault("raw_cat", {})[path.name] = r[ic]
    return meta


def find_pdfs() -> dict[str, Path]:
    out: dict[str, Path] = {}
    for d in sorted(PDF_ROOT.iterdir()):
        if d.is_dir():
            for f in sorted(d.glob("*.pdf")):
                out.setdefault(f.name, f)
    return out


def extract(path: Path) -> list[tuple[int, str]]:
    """返回 [(页码, 文本)]。

    优先 PyMuPDF：这批 PDF 有不少是当年从出版商站点抓取的，xref 表残缺、
    EOF 标记缺失。pypdf 对这类文件直接抛异常（92 篇里读不了 29 篇），
    PyMuPDF 会尽力修复后继续（只读不了 19 篇），多救回 10 篇。
    """
    pages: list[tuple[int, str]] = []
    try:
        import pymupdf  # 仅离线脚本依赖，不进 Web 服务的 requirements.txt

        with _quiet():
            doc = pymupdf.open(str(path))
            for i, pg in enumerate(doc, 1):
                t = pg.get_text() or ""
                if t.strip():
                    pages.append((i, t))
            doc.close()
        if pages:
            return pages
    except ImportError:
        pass
    except Exception:  # noqa: BLE001 — 退回 pypdf 再试一次
        pages = []

    from pypdf import PdfReader

    reader = PdfReader(str(path), strict=False)
    for i, pg in enumerate(reader.pages, 1):
        try:
            t = pg.extract_text() or ""
        except Exception:  # noqa: BLE001 — 单页解析失败不放弃整篇
            t = ""
        if t.strip():
            pages.append((i, t))
    return pages


class _quiet:
    """屏蔽 MuPDF 修复残缺 PDF 时刷屏的 stderr 告警。"""

    def __enter__(self):
        import os

        self._fd = os.dup(2)
        self._null = os.open(os.devnull, os.O_WRONLY)
        os.dup2(self._null, 2)

    def __exit__(self, *a):
        import os

        os.dup2(self._fd, 2)
        os.close(self._null)
        os.close(self._fd)


def guess_tier(meta: dict) -> str:
    """沿用旧的 ①②③④ 分级作为二级标签；catalog_all 的方向列映射过来。"""
    raw = meta.get("raw_cat", {})
    fm = raw.get("catalog_film_motor.xlsx")
    if fm:
        return str(fm).replace(" ", "")
    a = raw.get("catalog_all.xlsx")
    return {"电粘附": "③电粘附/夹持", "静电薄膜驱动器": "①核心·薄膜电机",
            "两者交叉": "③电粘附/夹持"}.get(a, "④外围")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", nargs="*", default=[], help="指定文件名，删掉旧记录后重新入库")
    a = ap.parse_args()

    con = sqlite3.connect(str(config.DB_PATH))
    con.row_factory = sqlite3.Row
    have = {r[0] for r in con.execute("SELECT file FROM papers")}
    disk = find_pdfs()
    meta = load_catalog_meta()

    todo = [f for f in sorted(disk) if f not in have or f in a.force]
    print(f"磁盘 {len(disk)} 篇 · 已索引 {len(have)} 篇 · 待入库 {len(todo)} 篇")
    print(f"catalog 元数据覆盖待入库的 {sum(1 for f in todo if f in meta)}/{len(todo)} 篇\n")
    if not todo:
        print("没有需要入库的文件。")
        return 0

    if not a.dry_run:
        shutil.copy2(config.DB_PATH, str(config.DB_PATH) + ".bak")
        print(f"已备份 → {config.DB_PATH}.bak\n")

    added_p = added_c = 0
    broken: list[tuple[str, str]] = []
    empty: list[str] = []

    for i, f in enumerate(todo, 1):
        path = disk[f]
        m = meta.get(f, {})
        try:
            pages = extract(path)
        except Exception as e:  # noqa: BLE001
            broken.append((f, f"{type(e).__name__}: {str(e)[:70]}"))
            print(f"  [{i:>3}/{len(todo)}] ✗ 损坏 {f[:52]}")
            continue
        chunks = [(p, s) for p, t in pages for s in split_page(t)]
        if not chunks:
            empty.append(f)
            print(f"  [{i:>3}/{len(todo)}] ✗ 抽不出文字(疑扫描件) {f[:44]}")
            continue

        title = m.get("title") or path.stem.replace("_", " ")
        year = m.get("year")
        try:
            year = int(str(year)[:4])
        except (TypeError, ValueError):
            mm = re.match(r"(\d{4})", f)
            year = int(mm.group(1)) if mm else None
        cited = m.get("cited")
        try:
            cited = int(cited)
        except (TypeError, ValueError):
            cited = None

        if not a.dry_run:
            if f in have:
                con.execute("DELETE FROM chunks WHERE file = ?", (f,))
                con.execute("DELETE FROM papers WHERE file = ?", (f,))
            con.execute(
                "INSERT INTO papers(file,title,authors,year,venue,doi,tier,cited,abstract) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (f, str(title)[:400], str(m.get("authors") or "")[:600], year,
                 str(m.get("venue") or "")[:200], str(m.get("doi") or ""),
                 guess_tier(m), cited, str(m.get("abstract") or "")[:4000]),
            )
            con.executemany(
                "INSERT INTO chunks(file,page,text,title) VALUES(?,?,?,?)",
                [(f, str(p), s, str(title)[:400]) for p, s in chunks],
            )
        added_p += 1
        added_c += len(chunks)
        if i % 10 == 0 or i == len(todo):
            print(f"  [{i:>3}/{len(todo)}] {added_p} 篇 / {added_c} 段  最新: {f[:44]}")

    if not a.dry_run:
        con.commit()

    print(f"\n{'（dry-run，未落盘）' if a.dry_run else '✓ 已写入'}")
    print(f"  新增论文 {added_p} 篇，新增段落 {added_c} 段")
    if broken:
        print(f"\n  ✗ {len(broken)} 篇 PDF 文件损坏，需重新下载：")
        for f, e in broken:
            print(f"      {f}\n        {e}")
    if empty:
        print(f"\n  ✗ {len(empty)} 篇抽不出文字（扫描件，需 OCR）：")
        for f in empty:
            print(f"      {f}")
    if not a.dry_run:
        n = con.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        nc = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        print(f"\n  库现状：papers {n} 篇 · chunks {nc} 段")
        print("  下一步：python scripts/build_vectors.py --incremental")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
