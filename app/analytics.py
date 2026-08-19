"""起始页的统计聚合。全部现算 —— 268 篇的量级，SQLite 几毫秒就出结果，
没必要做缓存表，也就不存在缓存过期的问题。"""
from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from typing import Optional

from . import config

# 作者名在不同期刊里写法不一：Toshiro Higuchi / T. Higuchi / Higuchi, T.
# 归一到「姓 + 名首字母」，否则同一个人会被拆成好几个统计项。
_NOISE_AUTHOR = re.compile(r"^\s*(et al\.?|and others|anonymous)\s*$", re.I)


def norm_author(raw: str) -> Optional[tuple[str, str]]:
    """返回 (归一键, 展示名)。认不出就返回 None。"""
    s = re.sub(r"\s+", " ", (raw or "").strip().strip(".,;"))
    if len(s) < 3 or _NOISE_AUTHOR.match(s):
        return None
    if "," in s:  # "Higuchi, Toshiro" 形式
        last, _, first = s.partition(",")
        last, first = last.strip(), first.strip()
    else:
        parts = s.split(" ")
        if len(parts) < 2:
            return None
        last, first = parts[-1], " ".join(parts[:-1])
    last = last.strip()
    if not last or len(last) < 2:
        return None
    key = f"{last.lower()}|{(first[:1] or '').lower()}"
    return key, f"{first} {last}".strip()


# 大模型抽出来的机构名写法不统一，不归并的话同一所会被拆成好几家 ——
# 实测「The University of Tokyo」26 篇和「University of Tokyo」20 篇被算成两所，
# 而东大合计 46 篇是这个领域的绝对重镇，拆开就完全看不出来了。
_INST_DROP = {"", "null", "none", "n/a", "na", "unknown", "-"}
_INST_PREFIX = re.compile(r"^(the|dept\.?|department of)\s+", re.I)
_INST_SUFFIX = re.compile(r"\s*[,，(（].*$")


def norm_inst(raw: Optional[str]) -> Optional[str]:
    s = re.sub(r"\s+", " ", (raw or "").strip())
    s = _INST_SUFFIX.sub("", s)          # 去掉逗号/括号后的院系、地址
    s = _INST_PREFIX.sub("", s).strip(" .,")
    if s.lower() in _INST_DROP or len(s) < 4:
        return None
    return s


# 地区归并：把下列代码统计进目标国家。
# 台湾、香港、澳门并入中国 —— 这是本库采用的统计口径，改这里即可调整。
# 地图渲染时这些地区也会跟着主体一起上色（见 index.html 的 MERGE_INTO）。
REGION_MERGE = {"TWN": "CHN", "HKG": "CHN", "MAC": "CHN"}


def canon_iso3(code: Optional[str]) -> Optional[str]:
    c = (code or "").strip().upper()
    if not c or len(c) != 3 or not c.isalpha() or c in ("NUL", "N/A", "NON", "UNK"):
        return None
    return REGION_MERGE.get(c, c)


def _conn(db=None) -> sqlite3.Connection:
    c = sqlite3.connect(str(db or config.DB_PATH), check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def _has(c, table: str) -> bool:
    return bool(c.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def overview(db=None, top_n: int = 20) -> dict:
    c = _conn(db)
    has_cat = "category" in {r[1] for r in c.execute("PRAGMA table_info(papers)")}
    cat_sel = "category" if has_cat else "'' AS category"

    papers = c.execute(
        f"SELECT file,title,authors,year,venue,doi,cited,tier,{cat_sel} FROM papers").fetchall()
    geo = {}
    if _has(c, "paper_geo"):
        geo = {r["file"]: dict(r) for r in c.execute("SELECT * FROM paper_geo")}

    # ---------- 总览 ----------
    total_cited = sum(int(p["cited"] or 0) for p in papers)
    years = [p["year"] for p in papers if p["year"] and 1900 < p["year"] < 2100]

    # ---------- 年度发文（按大类）----------
    by_year: dict[int, dict] = defaultdict(lambda: {"film_motor": 0, "electroadhesion": 0, "total": 0})
    for p in papers:
        y = p["year"]
        if not y or not (1900 < y < 2100):
            continue
        by_year[y]["total"] += 1
        if p["category"] in by_year[y]:
            by_year[y][p["category"]] += 1
    timeline = [{"year": y, **v} for y, v in sorted(by_year.items())]

    # ---------- 作者 ----------
    au: dict[str, dict] = {}
    for p in papers:
        names = [x for x in re.split(r"[,;]| and ", p["authors"] or "") if x.strip()]
        for i, raw in enumerate(names):
            n = norm_author(raw)
            if not n:
                continue
            key, disp = n
            a = au.setdefault(key, {"name": disp, "papers": 0, "cited": 0, "first": 0,
                                    "years": [], "cats": defaultdict(int)})
            a["papers"] += 1
            a["cited"] += int(p["cited"] or 0)
            if i == 0:
                a["first"] += 1
            if p["year"]:
                a["years"].append(p["year"])
            if p["category"]:
                a["cats"][p["category"]] += 1
            # 名字更长的那个写法更完整，用它做展示名
            if len(disp) > len(a["name"]):
                a["name"] = disp
    authors = []
    for a in au.values():
        ys = sorted(a["years"])
        authors.append({"name": a["name"], "papers": a["papers"], "cited": a["cited"],
                        "first_author": a["first"],
                        "span": f"{ys[0]}–{ys[-1]}" if ys else "",
                        "main_cat": max(a["cats"], key=a["cats"].get) if a["cats"] else ""})
    authors.sort(key=lambda x: (-x["papers"], -x["cited"]))

    # ---------- 机构 / 国别 ----------
    inst: dict[str, dict] = {}
    ctry: dict[str, dict] = {}
    for p in papers:
        g = geo.get(p["file"])
        if not g:
            continue
        name = norm_inst(g.get("institution"))
        if name:
            i = inst.setdefault(name.lower(), {"name": name, "papers": 0,
                                               "cited": 0, "country": g.get("country")})
            i["papers"] += 1
            i["cited"] += int(p["cited"] or 0)
        # canon_iso3 会滤掉模型返回的假国家码（"null" 被截成 "NUL" 那种），
        # 并按 REGION_MERGE 做地区归并
        k = canon_iso3(g.get("iso3"))
        if k:
            label = g.get("country") or k
            if canon_iso3(g.get("iso3")) != (g.get("iso3") or "").upper():
                label = "China"          # 归并进来的地区，显示为归并后的国名
            d = ctry.setdefault(k, {"iso3": k, "country": label,
                                    "papers": 0, "cited": 0,
                                    "film_motor": 0, "electroadhesion": 0})
            d["papers"] += 1
            d["cited"] += int(p["cited"] or 0)
            if p["category"] in d:
                d[p["category"]] += 1
    countries = sorted(ctry.values(), key=lambda x: -x["papers"])
    institutions = sorted(inst.values(), key=lambda x: (-x["papers"], -x["cited"]))[:top_n]

    # ---------- 高被引 ----------
    top_papers = sorted(
        [dict(p) for p in papers if p["cited"]],
        key=lambda p: -int(p["cited"] or 0))[:15]

    c.close()
    return {
        "totals": {
            "papers": len(papers),
            "cited": total_cited,
            "authors": len(authors),
            "institutions": len(inst),
            "countries": len(countries),
            "year_min": min(years) if years else None,
            "year_max": max(years) if years else None,
            "geo_coverage": sum(1 for g in geo.values() if g.get("iso3")),
        },
        "timeline": timeline,
        "authors": authors[:top_n],
        "institutions": institutions,
        "countries": countries,
        "top_papers": [{"title": p["title"], "year": p["year"], "cited": p["cited"],
                        "venue": p["venue"], "doi": p["doi"], "file": p["file"],
                        "category": p["category"]} for p in top_papers],
    }


# 单位统一到同一量纲才能横向比较：
#   推力密度 → N/cm²   （1 kN/m² = 0.1 N/cm²）
#   剪切/法向应力 → kPa（1 N/cm² = 10 kPa）
# 1 N/cm² = 10 kPa = 10 kN/m²；1 Pa = 1 N/m² = 1e-4 N/cm²
_TO_NCM2 = {"n/cm2": 1.0, "kn/m2": 0.1, "kpa": 0.1, "mpa": 100.0,
            "mn/cm2": 1e-3, "n/m2": 1e-4, "pa": 1e-4}
_TO_KPA = {"kpa": 1.0, "pa": 1e-3, "mpa": 1e3, "n/cm2": 10.0,
           "kn/m2": 1.0, "n/m2": 1e-3, "mn/cm2": 1e-2}

METRIC_LABEL = {
    "thrust_density": ("推力密度", "N/cm²"),
    "shear_stress": ("剪切强度", "kPa"),
    "normal_pressure": ("法向吸附压强", "kPa"),
    "thrust": ("推力", "N"),
    "holding_force": ("保持力", "N"),
    "speed": ("最大速度", "mm/s"),
    "efficiency": ("效率", "%"),
}


# 力和速度也必须换算 —— 之前这两类是原样透传的，导致 828 mN 被当成 828 N，
# 差了 1000 倍，直接毁掉整张图的量纲。
_TO_N = {"n": 1.0, "mn": 1e-3, "kn": 1e3, "μn": 1e-6, "un": 1e-6, "gf": 9.80665e-3,
         "kgf": 9.80665, "g": 9.80665e-3, "kg": 9.80665}
_TO_MMS = {"mm/s": 1.0, "m/s": 1e3, "cm/s": 10.0, "μm/s": 1e-3, "um/s": 1e-3,
           "mm/sec": 1.0, "m/min": 1e3 / 60}


def _convert(metric: str, value: float, unit: Optional[str]) -> Optional[float]:
    u = (unit or "").strip().lower().replace(" ", "").replace("^", "").replace("²", "2")
    if metric == "thrust_density":
        return value * _TO_NCM2[u] if u in _TO_NCM2 else None
    if metric in ("shear_stress", "normal_pressure"):
        return value * _TO_KPA[u] if u in _TO_KPA else None
    if metric in ("thrust", "holding_force"):
        return value * _TO_N[u] if u in _TO_N else None
    if metric == "speed":
        return value * _TO_MMS[u] if u in _TO_MMS else None
    if metric == "efficiency":
        if u not in ("%", "percent", ""):
            return None
        # 效率 >100% 物理上不可能，多半是把「提升 230%」当成了效率。宁可丢掉。
        return value if 0 < value <= 100 else None
    return None


def benchmarks(db=None) -> dict:
    """返回归一化后的性能数据点，每个点都带出处和实验条件。"""
    c = _conn(db)
    if not _has(c, "benchmark"):
        c.close()
        return {"available": False, "metrics": {}, "note": "尚未抽取，跑 scripts/extract_meta.py --what bench"}
    rows = c.execute(
        "SELECT b.*, p.title, p.year, p.category, p.doi FROM benchmark b "
        "JOIN papers p ON p.file = b.file").fetchall()
    c.close()

    out: dict[str, dict] = {}
    dropped = dedup = 0
    seen: set = set()
    for r in rows:
        m = r["metric"]
        if m not in METRIC_LABEL:
            continue
        v = _convert(m, r["value"], r["unit"])
        if v is None or v <= 0:
            dropped += 1        # 单位不认识就丢掉，不做猜测 —— 混进错单位的点会毁掉整张图
            continue
        # 同一篇的同一个数值会被抽到多次（每篇取了 3 段，同一个数常跨段重复出现），
        # 不去重的话散点图上会出现一串完全重叠的点，中位数也会被带偏
        key = (r["file"], m, round(v, 6), r["voltage_kv"], r["gap_um"])
        if key in seen:
            dedup += 1
            continue
        seen.add(key)
        d = out.setdefault(m, {"label": METRIC_LABEL[m][0], "unit": METRIC_LABEL[m][1], "points": []})
        d["points"].append({
            "value": round(v, 4), "raw": r["value"], "raw_unit": r["unit"],
            "voltage_kv": r["voltage_kv"], "gap_um": r["gap_um"], "medium": r["medium"],
            "note": r["note"], "title": r["title"], "year": r["year"],
            "category": r["category"], "file": r["file"], "page": r["page"], "doi": r["doi"],
        })
    for d in out.values():
        d["points"].sort(key=lambda p: -p["value"])
        vals = [p["value"] for p in d["points"]]
        n = len(vals)
        d["stats"] = {"n": n, "min": min(vals), "max": max(vals),
                      "median": sorted(vals)[n // 2]}
    if not out:
        # 表已建但没数据（跑过 --dry-run 就会这样），要和「表不存在」给一样的提示
        return {"available": False, "metrics": {},
                "note": "尚未抽取性能数据，跑 scripts/extract_meta.py --what bench 生成"}
    return {"available": True, "metrics": out, "dropped_unknown_unit": dropped, "deduped": dedup}
