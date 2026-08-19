#!/usr/bin/env python3
"""从 pygal_maps_world 的世界地图里烘出一份精简国界数据，供起始页画填色地图。

为什么要烘：起始页不能依赖任何 CDN（国内网络 + Render 都可能加载失败），
但把 778 KB 的原图整个塞进 HTML 又太重。这个脚本做三件事：
  1. 把贝塞尔曲线降为折线（只保留曲线端点，丢掉控制点）
  2. 丢掉面积过小的岛屿碎片
  3. 用 Douglas-Peucker 抽稀 + 降低坐标精度
输出 app/static/worldmap.js，约 60-90 KB，一次生成长期不变。

这是**构建期脚本**，只需跑一次；pygal_maps_world 不进 requirements.txt。

用法：
    pip install pygal_maps_world shapely
    python scripts/build_worldmap.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OUT = Path(__file__).resolve().parent.parent / "app" / "static" / "worldmap.js"

MIN_AREA = 8.0       # SVG 单位面积，低于此的碎片丢弃（viewBox 2475×1388）
TOLERANCE = 1.6      # Douglas-Peucker 抽稀容差
PREC = 1             # 坐标保留小数位

# 命令消耗的参数个数
ARGC = {"m": 2, "l": 2, "h": 1, "v": 2, "c": 6, "s": 4, "q": 4, "t": 2, "a": 7, "z": 0}
_NUM = re.compile(r"[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?")
_TOK = re.compile(r"([MmLlHhVvCcSsQqTtAaZz])|([-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?)")


def path_to_rings(d: str) -> list[list[tuple[float, float]]]:
    """把 SVG path 转成折线环。

    贝塞尔只取端点、圆弧只取终点 —— 在这个尺度上曲线弧度肉眼不可见，
    但点数能少一大半。这是有意的有损简化，不是偷懒。
    """
    toks = [(a or b) for a, b in _TOK.findall(d)]
    rings, cur = [], []
    x = y = sx = sy = 0.0
    i, cmd = 0, None
    while i < len(toks):
        t = toks[i]
        if re.match(r"[A-Za-z]", t):
            cmd = t
            i += 1
            if cmd in "Zz":
                if len(cur) >= 3:
                    rings.append(cur)
                cur = []
                x, y = sx, sy
            continue
        if cmd is None:
            i += 1
            continue
        rel = cmd.islower()
        k = cmd.lower()
        n = ARGC.get(k, 2)
        try:
            args = [float(v) for v in toks[i:i + n]]
        except ValueError:
            break
        if len(args) < n:
            break
        i += n
        if k == "m":
            x, y = (x + args[0], y + args[1]) if rel else (args[0], args[1])
            if len(cur) >= 3:
                rings.append(cur)
            cur = [(x, y)]
            sx, sy = x, y
            cmd = "l" if rel else "L"      # moveto 之后的连续坐标按 lineto 处理
            continue
        if k == "l":
            x, y = (x + args[0], y + args[1]) if rel else (args[0], args[1])
        elif k == "h":
            x = x + args[0] if rel else args[0]
        elif k == "v":
            y = y + args[0] if rel else args[0]
        elif k in ("c", "s", "q", "t", "a"):
            ex, ey = args[-2], args[-1]     # 只要终点
            x, y = (x + ex, y + ey) if rel else (ex, ey)
        cur.append((x, y))
    if len(cur) >= 3:
        rings.append(cur)
    return rings


def main() -> int:
    try:
        import pygal_maps_world as pw
        from shapely.geometry import Polygon
    except ImportError:
        print("需要： pip install pygal_maps_world shapely")
        return 1

    src = Path(os.path.dirname(pw.__file__)) / "worldmap.svg"
    svg = src.read_text(encoding="utf-8")
    vb = re.search(r'viewBox="([^"]+)"', svg).group(1)
    groups = re.findall(r'<g class="([a-z_]{2,3}) country map-element">(.*?)</g>', svg, re.S)
    print(f"源文件 {src.stat().st_size / 1024:.0f} KB · {len(groups)} 个国家 · viewBox {vb}")

    out, centroids = {}, {}
    kept = dropped = 0
    for iso2, body in groups:
        polys = []
        for d in re.findall(r'd="([^"]+)"', body):
            for ring in path_to_rings(d):
                try:
                    p = Polygon(ring)
                    if not p.is_valid:
                        p = p.buffer(0)
                    if p.is_empty or p.area < MIN_AREA:
                        dropped += 1
                        continue
                    p = p.simplify(TOLERANCE, preserve_topology=True)
                    if p.is_empty:
                        continue
                    polys.append(p)
                    kept += 1
                except Exception:  # noqa: BLE001 — 个别畸形环直接跳过
                    dropped += 1
        if not polys:
            # 新加坡、香港、马耳他这类城市国家面积太小、全被过滤掉了。
            # 画不出轮廓，但仍要保留质心 —— 否则它们在地图上彻底消失，
            # 而这几个地方恰恰是有产出的（新加坡 11 篇）。前端会退化成画一个点。
            pts = [p for d in re.findall(r'd="([^"]+)"', body) for r in path_to_rings(d) for p in r]
            if pts:
                centroids[iso2] = [round(sum(p[0] for p in pts) / len(pts), 1),
                                   round(sum(p[1] for p in pts) / len(pts), 1)]
            continue
        segs = []
        for p in polys:
            for geom in (p.geoms if p.geom_type == "MultiPolygon" else [p]):
                cs = list(geom.exterior.coords)
                if len(cs) < 4:
                    continue
                segs.append("M" + "L".join(f"{round(a, PREC)} {round(b, PREC)}" for a, b in cs) + "Z")
        if not segs:
            continue
        out[iso2] = "".join(segs)
        # 质心取面积最大的那块陆地 —— 用全部陆地的平均会把美国算到太平洋里
        big = max(polys, key=lambda p: p.area)
        c = big.representative_point()
        centroids[iso2] = [round(c.x, 1), round(c.y, 1)]

    # 数据库里存的是 ISO3（extract_meta.py 抽的），地图用 ISO2，需要一张对照表。
    # 顺便带上中文国名，页面上不用再维护一份。
    i2, names = {}, {}
    try:
        import pycountry

        for c in pycountry.countries:
            a2 = c.alpha_2.lower()
            if a2 in centroids:
                i2[c.alpha_3] = a2
                names[c.alpha_3] = getattr(c, "common_name", None) or c.name
    except ImportError:
        print("  ⚠ 未装 pycountry，ISO3→ISO2 对照表为空（pip install pycountry 后重跑）")
    # pygal 用 gb 表示英国、把台港澳单列；ISO3 侧需要手工补上
    i2.setdefault("GBR", "gb")
    for a3, a2 in (("TWN", "tw"), ("HKG", "hk"), ("MAC", "mo")):
        if a2 in centroids:
            i2.setdefault(a3, a2)
    print(f"ISO3→ISO2 对照 {len(i2)} 条")

    js = ("// 由 scripts/build_worldmap.py 从 pygal_maps_world 生成，勿手改。\n"
          "// 贝塞尔已降为折线、小岛已丢弃、坐标已抽稀 —— 仅供缩略展示，非精确边界。\n"
          f"window.WORLD = {{viewBox:{json.dumps(vb)}, "
          f"paths:{json.dumps(out, separators=(',', ':'))}, "
          f"centroids:{json.dumps(centroids, separators=(',', ':'))}, "
          f"iso3to2:{json.dumps(i2, separators=(',', ':'))}, "
          f"names:{json.dumps(names, separators=(',', ':'), ensure_ascii=False)}}};\n")
    OUT.write_text(js, encoding="utf-8")
    print(f"保留多边形 {kept}，丢弃碎片 {dropped}")
    print(f"✓ 已写出 {OUT}  {OUT.stat().st_size / 1024:.0f} KB  覆盖 {len(out)} 个国家/地区")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
