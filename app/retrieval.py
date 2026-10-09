"""混合检索：FTS5 关键词路 + 向量语义路，用 RRF 融合。

为什么用 RRF 而不是加权分数相加：BM25 分数和余弦相似度量纲完全不同
（前者无上界、依赖语料统计；后者恒在 [-1,1]），直接线性组合需要精调归一化
参数，换个查询就失效。RRF 只看名次不看分数，天然免疫量纲问题，也是学界
在混合检索上的默认基线。
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections import defaultdict
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from . import config

log = logging.getLogger(__name__)

# FTS5 的 unicode61 分词器对中文几乎不切分，中文查询基本命中不了英文文献 ——
# 这正是向量路存在的意义。停用词只挡最没有区分度的那批。
_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were",
    "has", "have", "had", "not", "but", "its", "it's", "can", "will", "how",
    "what", "why", "which", "when", "who", "does", "did", "you", "your",
    "请", "帮我", "介绍", "一下", "什么", "怎么", "如何", "是否", "以及", "关于",
}
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-_.]*|\d+(?:\.\d+)?|[一-鿿]+")


def tokenize(q: str) -> List[str]:
    out = []
    for t in _TOKEN_RE.findall(q or ""):
        if t.lower() in _STOP:
            continue
        if len(t) < 2 and not t.isdigit():
            continue
        out.append(t)
    return out


def build_fts_query(q: str, mode: str = "OR") -> Optional[str]:
    """把自然语言转成安全的 FTS5 查询串。

    每个词单独加双引号当短语处理 —— 这一步是必须的：用户输入里的
    `-` `*` `:` `(` `"` `NEAR` `AND` 都是 FTS5 的语法元素，不转义会直接抛
    `sqlite3.OperationalError: fts5: syntax error`，是这类项目最常见的线上崩溃。

    默认 OR：自然语言提问用 AND 几乎必然零召回，OR 交给 BM25 排序，
    命中词多的段落自然排在前面。
    """
    toks = tokenize(q)
    if not toks:
        return None
    quoted = ['"' + t.replace('"', '""') + '"' for t in toks]
    return f" {mode} ".join(quoted)


def _tier_like(tier: Optional[str]) -> Optional[str]:
    """把 '1' / '①' / '①核心' 统一成 LIKE 模式。"""
    if not tier:
        return None
    t = config.TIER_MAP.get(str(tier), str(tier))
    return f"%{t}%"


@dataclass
class Hit:
    rowid: int
    file: str
    page: str
    title: str
    authors: str
    year: Optional[int]
    venue: str
    doi: str
    tier: str
    category: str
    cross_topic: int
    cited: Optional[int]
    text: str
    preview: str
    score: float
    routes: Dict[str, int] = field(default_factory=dict)  # 路名 -> 该路名次，便于调参时看两路各自贡献

    def to_dict(self) -> dict:
        return asdict(self)


def _preview(text: str, toks: Sequence[str], width: int = 340) -> str:
    """截取包含查询词的片段并用 【】 标出，纯向量命中（无词匹配）时退回开头。"""
    if not text:
        return ""
    low = text.lower()
    pos = -1
    for t in toks:
        p = low.find(t.lower())
        if p >= 0 and (pos < 0 or p < pos):
            pos = p
    start = 0 if pos < 0 else max(0, pos - width // 3)
    seg = text[start: start + width].replace("\n", " ").strip()
    for t in sorted(set(toks), key=len, reverse=True):
        seg = re.sub(f"({re.escape(t)})", r"【\1】", seg, flags=re.IGNORECASE)
    return ("…" if start > 0 else "") + seg + ("…" if start + width < len(text) else "")


def rrf_fuse(
    ranked_lists: Sequence[Tuple[str, Sequence[int], float]],
    k: int = config.RRF_K,
) -> List[Tuple[int, float, Dict[str, int]]]:
    """倒数排名融合。

    ranked_lists: [(路名, 按相关性降序的 rowid 列表, 权重), ...]
    score(d) = Σ_路 weight / (k + rank_路(d))，rank 从 1 起。
    k=60 是惯例值，作用是压低头部名次之间的差距，避免单路的第 1 名
    压过另一路的第 2、3 名 —— 让"两路都排前面"的结果胜出，这正是混合检索要的。
    """
    scores: Dict[int, float] = defaultdict(float)
    routes: Dict[int, Dict[str, int]] = defaultdict(dict)
    for name, ids, weight in ranked_lists:
        for rank, rid in enumerate(ids, start=1):
            scores[rid] += weight / (k + rank)
            routes[rid][name] = rank
    fused = sorted(scores.items(), key=lambda kv: -kv[1])
    return [(rid, sc, routes[rid]) for rid, sc in fused]


class Index:
    """启动时加载一次，全进程复用。向量 6344×1024 float32 ≈ 26 MB，常驻内存无压力。"""

    EMBED_FAIL_LIMIT = 3   # 连续这么多次向量化失败就熔断向量路

    def __init__(self, db_path=None, vec_path=None):
        self.db_path = str(db_path or config.DB_PATH)
        self.vectors: Optional[np.ndarray] = None
        self.vec_rowids: Optional[np.ndarray] = None
        self.vec_tiers: Optional[np.ndarray] = None   # 与 vectors 行对齐的 tier
        self.vec_cats: Optional[np.ndarray] = None    # 与 vectors 行对齐的 category
        self.vec_meta: dict = {}
        self._embed_fails = 0
        self._embed_down = False
        self.has_category = self._has_category_col()
        if not self.has_category:
            raise RuntimeError("索引缺少 category 字段，请先分类再部署")
        self._load_vectors(vec_path or config.VEC_PATH)

    # ---------- 加载 ----------
    def _load_vectors(self, vec_path) -> None:
        import os

        if not os.path.exists(vec_path):
            log.warning("未找到 %s —— 降级为纯关键词检索。跑 scripts/build_vectors.py 生成。", vec_path)
            return
        self.vectors = np.load(vec_path).astype(np.float32)
        # meta 必须跟着 vec_path 走。用默认路径的 meta 去配自定义向量文件，
        # 会把行号和 rowid 错配 —— 那是最难查的一类 bug（检索结果全是对的格式、错的内容）。
        vp = Path(vec_path)
        meta_path = (config.VEC_META_PATH if vp == Path(config.VEC_PATH)
                     else vp.with_suffix(".meta.json"))
        try:
            self.vec_meta = json.loads(Path(meta_path).read_text(encoding="utf-8"))
            self.vec_rowids = np.asarray(self.vec_meta["rowids"], dtype=np.int64)
        except Exception:  # noqa: BLE001 — 没有 meta 就假定行号 == rowid 升序
            log.warning("缺少 %s，假定向量行序 == chunks.rowid 升序", meta_path)
            with self.conn() as c:
                ids = [r[0] for r in c.execute("SELECT rowid FROM chunks ORDER BY rowid")]
            self.vec_rowids = np.asarray(ids[: len(self.vectors)], dtype=np.int64)
        if len(self.vec_rowids) != len(self.vectors):
            raise RuntimeError(
                f"向量数({len(self.vectors)})与 rowid 数({len(self.vec_rowids)})不一致，请重跑 build_vectors.py"
            )
        # 预取每行对应的 category / tier，向量路才能做同样的过滤
        cat_sel = "p.category" if self.has_category else "''"
        with self.conn() as c:
            m = {r[0]: (r[1] or "", r[2] or "") for r in c.execute(
                f"SELECT ch.rowid, p.tier, {cat_sel} FROM chunks ch "
                f"LEFT JOIN papers p ON p.file = ch.file"
            )}
        self.vec_tiers = np.array([m.get(int(r), ("", ""))[0] for r in self.vec_rowids], dtype=object)
        self.vec_cats = np.array([m.get(int(r), ("", ""))[1] for r in self.vec_rowids], dtype=object)
        log.info("已加载向量 %s，模型=%s", self.vectors.shape, self.vec_meta.get("model", "?"))

    def _has_category_col(self) -> bool:
        """兼容尚未跑 recategorize.py 的旧库 —— 没有 category 列时分类筛选自动失效而不报错。"""
        with self.conn() as c:
            return "category" in {r[1] for r in c.execute("PRAGMA table_info(papers)")}

    @property
    def has_vectors(self) -> bool:
        return self.vectors is not None

    def conn(self) -> sqlite3.Connection:
        # SQLite 只读并发没问题；每次请求开新连接比共享连接更安全
        c = sqlite3.connect(self.db_path, check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

    # ---------- 单路检索 ----------
    def keyword_search(self, query: str, k: int = config.K_KEYWORD, tier: Optional[str] = None,
                       category: Optional[str] = None) -> List[int]:
        if category not in (None, config.FM):
            return []
        category = config.FM
        fq = build_fts_query(query)
        if not fq:
            return []
        sql = ("SELECT ch.rowid AS rid FROM chunks ch JOIN papers p ON p.file = ch.file "
               "WHERE chunks MATCH ?")
        args: list = [fq]
        if category and self.has_category:
            # 网站只开放主分类为 film_motor 的论文，交叉标记不扩大范围。
            sql += " AND p.category = ?"
            args.append(category)
        like = _tier_like(tier)
        if like:
            sql += " AND p.tier LIKE ?"
            args.append(like)
        sql += " ORDER BY rank LIMIT ?"
        args.append(k)
        try:
            with self.conn() as c:
                return [r["rid"] for r in c.execute(sql, args)]
        except sqlite3.OperationalError as e:
            log.error("FTS5 查询失败 query=%r fts=%r: %s", query, fq, e)
            return []

    def vector_search(self, query: str, k: int = config.K_VECTOR, tier: Optional[str] = None,
                      category: Optional[str] = None) -> List[int]:
        if category not in (None, config.FM):
            return []
        category = config.FM
        if not self.has_vectors or self._embed_down:
            return []
        from .embed import embed_query

        try:
            qv = embed_query(query)
            self._embed_fails = 0
        except Exception as e:  # noqa: BLE001 — 向量路挂了不能拖垮整个检索
            self._embed_fails += 1
            log.error("查询向量化失败(%d/%d)，本次仅用关键词路：%s",
                      self._embed_fails, self.EMBED_FAIL_LIMIT, e)
            # 熔断：embedding 服务挂了就别每个查询都白等 5 次退避重试（约 30 秒）。
            # 连续失败到阈值后直接停用向量路，降级成纯关键词，保证服务仍然可用。
            if self._embed_fails >= self.EMBED_FAIL_LIMIT:
                self._embed_down = True
                log.error("向量路已熔断，本进程后续查询仅用关键词路。修复后重启服务恢复。")
            return []
        sims = self.vectors @ qv  # 已归一化 → 点积即余弦
        mask = None

        def _and(m):
            nonlocal mask
            mask = m if mask is None else (mask & m)

        if category and self.has_category and self.vec_cats is not None:
            _and(np.array([c == category for c in self.vec_cats]))
        like = _tier_like(tier)
        if like:
            token = like.strip("%")
            _and(np.array([token in (t or "") for t in self.vec_tiers]))
        if mask is not None:
            if not mask.any():
                return []
            sims = np.where(mask, sims, -np.inf)
        n = min(k, int(mask.sum()) if mask is not None else len(sims))
        if n <= 0:
            return []
        top = np.argpartition(-sims, n - 1)[:n]          # 只做部分排序，比全排快一个量级
        top = top[np.argsort(-sims[top])]
        return [int(self.vec_rowids[i]) for i in top]

    # ---------- 融合 ----------
    def search(
        self,
        query: str,
        k_final: int = config.K_FINAL,
        tier: Optional[str] = None,
        year_min: Optional[int] = None,
        year_max: Optional[int] = None,
        category: Optional[str] = None,
    ) -> List[Hit]:
        kw = self.keyword_search(query, config.K_KEYWORD, tier, category)
        vec = self.vector_search(query, config.K_VECTOR, tier, category)
        fused = rrf_fuse([
            ("keyword", kw, config.W_KEYWORD),
            ("vector", vec, config.W_VECTOR),
        ])
        if not fused:
            return []
        # 年份过滤放在融合之后：先保证两路排名不被稀释，再筛。
        # 多取一些候选，防止过滤后不够 k_final。
        cand = fused[: max(k_final * 5, 40)]
        hits = self._hydrate([r for r, _, _ in cand], query)
        by_id = {h.rowid: h for h in hits}
        out: List[Hit] = []
        for rid, score, routes in cand:
            h = by_id.get(rid)
            if h is None:
                continue
            if year_min and (h.year or 0) < year_min:
                continue
            if year_max and (h.year or 9999) > year_max:
                continue
            h.score, h.routes = round(score, 6), routes
            out.append(h)
            if len(out) >= k_final:
                break
        return out

    def _hydrate(self, rowids: Iterable[int], query: str) -> List[Hit]:
        ids = list(rowids)
        if not ids:
            return []
        toks = tokenize(query)
        ph = ",".join("?" * len(ids))
        extra = "p.category, p.cross_topic" if self.has_category else "'' AS category, 0 AS cross_topic"
        sql = (f"SELECT ch.rowid AS rid, ch.file, ch.page, ch.text, "
               f"p.title, p.authors, p.year, p.venue, p.doi, p.tier, p.cited, {extra} "
               f"FROM chunks ch LEFT JOIN papers p ON p.file = ch.file "
               f"WHERE ch.rowid IN ({ph}) AND p.category = 'film_motor'")
        with self.conn() as c:
            rows = c.execute(sql, ids).fetchall()
        return [
            Hit(
                rowid=r["rid"], file=r["file"] or "", page=str(r["page"] or ""),
                title=r["title"] or "(无标题)", authors=r["authors"] or "",
                year=r["year"], venue=r["venue"] or "", doi=r["doi"] or "",
                tier=r["tier"] or "", category=r["category"] or "",
                cross_topic=int(r["cross_topic"] or 0),
                cited=r["cited"], text=r["text"] or "",
                preview=_preview(r["text"] or "", toks), score=0.0,
            )
            for r in rows
        ]

    # ---------- 元数据 ----------
    def stats(self) -> dict:
        cats = []
        with self.conn() as c:
            papers = c.execute("SELECT COUNT(*) FROM papers WHERE category='film_motor'").fetchone()[0]
            chunks = c.execute("SELECT COUNT(*) FROM chunks ch JOIN papers p ON p.file=ch.file WHERE p.category='film_motor'").fetchone()[0]
            tiers = [dict(tier=r[0] or "未分级", n=r[1]) for r in c.execute(
                "SELECT tier, COUNT(*) n FROM papers WHERE category='film_motor' GROUP BY tier ORDER BY n DESC")]
            ymin, ymax = c.execute("SELECT MIN(year), MAX(year) FROM papers WHERE category='film_motor' AND year > 1900").fetchone()
            if self.has_category:
                for key, cfg in config.CATEGORIES.items():
                    n, nc, seg = c.execute(
                        "SELECT COUNT(*), SUM(COALESCE(p.cross_topic,0)), "
                        "(SELECT COUNT(*) FROM chunks ch JOIN papers q ON q.file=ch.file "
                        " WHERE q.category=?) "
                        "FROM papers p WHERE p.category = ?", (key, key)).fetchone()
                    cats.append({"key": key, **cfg, "papers": n or 0,
                                 "cross": nc or 0, "chunks": seg or 0})
        return {
            "papers": papers, "chunks": chunks, "tiers": tiers, "categories": cats,
            "has_category": self.has_category,
            "year_min": ymin, "year_max": ymax,
            "vectors": int(np.count_nonzero(self.vec_cats == config.FM)) if self.has_vectors else 0,
            "embed_model": self.vec_meta.get("model"),
            "mode": "hybrid" if self.has_vectors else "keyword-only",
        }

    def paper(self, file: str) -> Optional[dict]:
        with self.conn() as c:
            p = c.execute("SELECT * FROM papers WHERE file = ? AND category='film_motor'", (file,)).fetchone()
            if not p:
                return None
            segs = c.execute(
                "SELECT rowid AS rid, page, text FROM chunks WHERE file = ? ORDER BY CAST(page AS INTEGER), rowid",
                (file,),
            ).fetchall()
        return {**dict(p), "segments": [dict(s) for s in segs]}
