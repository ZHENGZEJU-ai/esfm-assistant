#!/usr/bin/env python3
"""用大模型从全文里抽两类结构化数据，写进数据库供起始页展示。

  1. 机构与国别  ← 论文首页的通讯地址。库里原本没有这个字段，
                    地域热力图完全依赖它。
  2. 性能指标    ← 推力密度 / 剪切强度 / 驱动电压 / 电极间距 等，
                    **连同实验条件一起抽** —— 静电驱动的性能数据脱离
                    气压、介质、间距就没有意义，只存一个数字等于造假。

用法：
    python scripts/extract_meta.py --what geo    --dry-run
    python scripts/extract_meta.py --what geo            # 268 篇，约 ¥0.5
    python scripts/extract_meta.py --what bench          # 约 ¥2
    python scripts/extract_meta.py --what all --workers 4

断点续传：已抽过的论文自动跳过，中断了重跑即可。
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402

GEO_SYS = """你从论文首页文字里提取**第一作者或通讯作者所属机构**的信息。

只输出一行 JSON，不要解释：
{"institution":"机构英文全称","country":"国家英文名","iso3":"ISO 3166-1 三字母代码","city":"城市或null"}

规则：
- 认不出来就全部填 null，不要猜。宁可缺数据也不要错数据。
- 日文/中文机构名转成通用英文名（例：東京大学 → University of Tokyo）。
- 国家用常见英文名：Japan / China / United States / South Korea / Germany / Switzerland ...
- iso3 例：JPN, CHN, USA, KOR, DEU, CHE, GBR, FRA, ITA, NLD, CAN, SGP, IND, TUR, IRN。
- 台湾地区填 country="China", iso3="TWN"；香港填 country="China", iso3="HKG"。"""

BENCH_SYS = """你从静电驱动/静电吸附论文的正文片段里提取**实测性能指标**。

只输出一个 JSON 数组，不要解释。没有可靠数据就输出 []。

每条格式：
{"metric":"指标名","value":数字,"unit":"单位","voltage_kv":数字或null,
 "gap_um":数字或null,"medium":"air/oil/vacuum/liquid/null","note":"20字内补充"}

metric 只能取这几个值之一：
  thrust_density   推力密度（单位 N/cm2 或 kN/m2）
  thrust           绝对推力（N）
  shear_stress     剪切强度/剪切应力（kPa）
  normal_pressure  法向吸附压强（kPa）
  holding_force    保持力（N）
  speed            最大速度（mm/s）
  efficiency       效率（%）

硬性要求：
- 只提取论文**自己实测或明确报告**的数值，不要提取它引用别人的、也不要提取理论预测值。
- 数值必须能在片段里找到出处，不允许推算或估计。
- voltage_kv / gap_um 填该数值对应的实验条件，片段里没写就填 null，不要从别处推断。
- 同一指标有多个工况就输出多条。"""


def ensure_tables(con):
    con.execute("""CREATE TABLE IF NOT EXISTS paper_geo(
        file TEXT PRIMARY KEY, institution TEXT, country TEXT, iso3 TEXT, city TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS benchmark(
        id INTEGER PRIMARY KEY AUTOINCREMENT, file TEXT, page TEXT, metric TEXT,
        value REAL, unit TEXT, voltage_kv REAL, gap_um REAL, medium TEXT, note TEXT)""")
    con.execute("CREATE INDEX IF NOT EXISTS ix_bench_file ON benchmark(file)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_bench_metric ON benchmark(metric)")
    con.commit()


def ask_json(system: str, user: str, retries: int = 2):
    from app import llm

    for _ in range(retries):
        try:
            raw = llm.chat([{"role": "system", "content": system},
                            {"role": "user", "content": user}],
                           temperature=0.0, max_tokens=700)
            s, e = raw.find("["), raw.rfind("]")
            if s < 0:
                s, e = raw.find("{"), raw.rfind("}")
            if s >= 0:
                return json.loads(raw[s:e + 1])
        except Exception:  # noqa: BLE001
            continue
    return None


# ---------- 机构 / 国别 ----------
def run_geo(con, workers, dry):
    done = {r[0] for r in con.execute("SELECT file FROM paper_geo")}
    rows = con.execute(
        "SELECT p.file, p.title, (SELECT text FROM chunks ch WHERE ch.file=p.file "
        "ORDER BY CAST(ch.page AS INT), ch.rowid LIMIT 1) t FROM papers p").fetchall()
    todo = [r for r in rows if r[0] not in done and r[2]]
    print(f"机构国别：{len(rows)} 篇，已抽 {len(done)}，待抽 {len(todo)}")
    print(f"预估 ≈¥{len(todo) * 0.0015:.2f}")
    if dry or not todo:
        return
    lock = threading.Lock()
    cnt = {"ok": 0, "null": 0}

    def one(r):
        f, title, txt = r
        # 只给首页前 1500 字 —— 通讯地址几乎总在这个范围内，给多了反而干扰
        js = ask_json(GEO_SYS, f"标题：{title}\n\n首页文字：\n{(txt or '')[:1500]}")
        if not isinstance(js, dict):
            return
        # 模型偶尔把「认不出来」写成字符串 "null"/"N/A" 而不是 JSON null。
        # 不清理的话 "null" 会被截成 "NUL"，在地图上变成一个不存在的国家。
        def clean(v):
            s = str(v or "").strip()
            return None if s.lower() in ("", "null", "none", "n/a", "na", "unknown", "-") else s

        iso3 = clean(js.get("iso3"))
        iso3 = iso3.upper()[:3] if iso3 and len(iso3) == 3 and iso3.isalpha() else None
        with lock:
            con.execute("INSERT OR REPLACE INTO paper_geo VALUES(?,?,?,?,?)",
                        (f, clean(js.get("institution")), clean(js.get("country")),
                         iso3, clean(js.get("city"))))
            if js.get("iso3"):
                cnt["ok"] += 1
            else:
                cnt["null"] += 1
            n = cnt["ok"] + cnt["null"]
            if n % 10 == 0:
                con.commit()
            print(f"\r  {n}/{len(todo)}  识别出国别 {cnt['ok']}  未识别 {cnt['null']}", end="", flush=True)

    _parallel(one, todo, workers)
    con.commit()
    print()


# ---------- 性能指标 ----------
NUM_HINT = re.compile(
    r"(N/cm|kN/m|mN|kPa|MPa|thrust|shear|holding force|adhesion force|force density|"
    r"mm/s|efficiency)", re.I)


def run_bench(con, workers, dry):
    done = {r[0] for r in con.execute("SELECT DISTINCT file FROM benchmark")}
    # 只挑「像有数据」的段落，别把整库 6344 段都送进模型
    cand = con.execute(
        "SELECT ch.file, ch.page, ch.text FROM chunks ch JOIN papers p ON p.file=ch.file "
        "WHERE (ch.text LIKE '%N/cm%' OR ch.text LIKE '%kN/m%' OR ch.text LIKE '%kPa%' "
        "   OR ch.text LIKE '%thrust%' OR ch.text LIKE '%shear%' OR ch.text LIKE '%holding force%') "
        "ORDER BY ch.file, CAST(ch.page AS INT)").fetchall()
    byfile = {}
    for f, pg, t in cand:
        if f in done or not NUM_HINT.search(t or ""):
            continue
        byfile.setdefault(f, []).append((pg, t))
    todo = list(byfile.items())
    print(f"性能指标：{len(cand)} 个候选段落，覆盖 {len(byfile)} 篇未抽论文")
    print(f"预估 ≈¥{sum(min(3, len(v)) for _, v in todo) * 0.004:.2f}")
    if dry or not todo:
        return
    lock = threading.Lock()
    cnt = {"papers": 0, "rows": 0}

    def one(item):
        f, segs = item
        # 每篇最多取 3 段最像有数据的，避免成本失控
        segs = sorted(segs, key=lambda s: -len(NUM_HINT.findall(s[1])))[:3]
        got = 0
        for pg, t in segs:
            js = ask_json(BENCH_SYS, t[:3500])
            if not isinstance(js, list):
                continue
            with lock:
                for d in js:
                    try:
                        v = float(d["value"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    con.execute(
                        "INSERT INTO benchmark(file,page,metric,value,unit,voltage_kv,gap_um,medium,note)"
                        " VALUES(?,?,?,?,?,?,?,?,?)",
                        (f, str(pg), d.get("metric"), v, d.get("unit"),
                         _f(d.get("voltage_kv")), _f(d.get("gap_um")),
                         d.get("medium"), (d.get("note") or "")[:60]))
                    got += 1
        with lock:
            cnt["papers"] += 1
            cnt["rows"] += got
            if cnt["papers"] % 5 == 0:
                con.commit()
            print(f"\r  {cnt['papers']}/{len(todo)} 篇  已抽出 {cnt['rows']} 条指标", end="", flush=True)

    _parallel(one, todo, workers)
    con.commit()
    print()


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _parallel(fn, items, workers):
    if workers > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(fn, items))
    else:
        for it in items:
            fn(it)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--what", choices=["geo", "bench", "all"], default="all")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if not a.dry_run and not config.PROVIDERS[config.LLM_PROVIDER]["api_key"]:
        print("✗ 未配置对话模型 API Key")
        return 1

    con = sqlite3.connect(str(config.DB_PATH), check_same_thread=False)
    ensure_tables(con)
    if a.what in ("geo", "all"):
        run_geo(con, a.workers, a.dry_run)
    if a.what in ("bench", "all"):
        run_bench(con, a.workers, a.dry_run)

    if not a.dry_run:
        g = con.execute("SELECT COUNT(*), COUNT(iso3) FROM paper_geo").fetchone()
        b = con.execute("SELECT COUNT(*), COUNT(DISTINCT file) FROM benchmark").fetchone()
        print(f"\n✓ paper_geo: {g[0]} 篇，其中 {g[1]} 篇识别出国别")
        print(f"✓ benchmark: {b[0]} 条指标，来自 {b[1]} 篇论文")
        top = con.execute("SELECT iso3, COUNT(*) n FROM paper_geo WHERE iso3 IS NOT NULL "
                          "GROUP BY iso3 ORDER BY n DESC LIMIT 8").fetchall()
        print("  国别 top8:", dict(top))
        print("\n重启 uvicorn 后起始页即可看到数据")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
