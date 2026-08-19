"""FastAPI 入口。

/api/stats        库统计
/api/search       纯检索（不花钱，用来调检索参数）
/api/ask          RAG 问答，SSE 流式
/api/paper/{file} 单篇论文元数据 + 全部段落
"""
from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, llm
from .prompts import build_messages
from .retrieval import Index

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("esfm")

STATIC = Path(__file__).parent / "static"
INDEX: Optional[Index] = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """向量在启动时一次性载入内存（14 MB），之后所有请求复用。"""
    global INDEX
    INDEX = Index()
    log.info("索引就绪：%s", INDEX.stats())
    yield


app = FastAPI(title="静电薄膜电机知识助手", version="0.1.0", lifespan=lifespan)


def _idx() -> Index:
    if INDEX is None:
        raise HTTPException(503, "索引尚未就绪")
    return INDEX


class SearchReq(BaseModel):
    query: str
    k: int = config.K_FINAL
    category: Optional[str] = None   # film_motor / electroadhesion，None=全部
    tier: Optional[str] = None
    year_min: Optional[int] = None
    year_max: Optional[int] = None
    expand: bool = False


class AskReq(SearchReq):
    k: int = config.K_FINAL
    expand: bool = True
    provider: Optional[str] = None


@app.get("/api/stats")
def stats():
    return {**_idx().stats(), "providers": llm.available(),
            "provider": config.LLM_PROVIDER, "local_pdf": bool(config.LOCAL_PDF_ROOT)}


@app.post("/api/search")
def search(r: SearchReq):
    q = llm.expand_query(r.query) if r.expand else r.query
    hits = _idx().search(q, r.k, r.tier, r.year_min, r.year_max, r.category)
    return {"query": r.query, "expanded": q if q != r.query else None,
            "count": len(hits), "hits": [h.to_dict() for h in hits]}


@app.post("/api/ask")
def ask(r: AskReq):
    idx = _idx()

    def sse():
        def ev(t, d):
            return f"event: {t}\ndata: {json.dumps(d, ensure_ascii=False)}\n\n"

        try:
            q = llm.expand_query(r.query) if r.expand else r.query
            hits = idx.search(q, r.k, r.tier, r.year_min, r.year_max, r.category)
            # 先把引用推给前端 —— 用户在模型还没吐第一个字时就能看到召回了什么，
            # Render 免费层冷启动慢，这个体验差异很明显
            yield ev("sources", {"expanded": q if q != r.query else None,
                                 "hits": [h.to_dict() for h in hits]})
            if not hits:
                yield ev("token", {"t": "文献库中未检索到相关内容。可以试试换用英文术语，或放宽分级筛选。"})
                yield ev("done", {})
                return
            for tok in llm.stream_chat(build_messages(r.query, hits), provider=r.provider):
                yield ev("token", {"t": tok})
            yield ev("done", {})
        except Exception as e:  # noqa: BLE001
            log.exception("ask 失败")
            yield ev("error", {"msg": str(e)})

    return StreamingResponse(sse(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/paper/{file}")
def paper(file: str):
    p = _idx().paper(file)
    if not p:
        raise HTTPException(404, "未找到该论文")
    return p


@app.get("/api/pdf/{file}")
def pdf(file: str):
    """只在本地设了 LOCAL_PDF_ROOT 时可用；线上没有 PDF，返回 404 由前端引导去 DOI。"""
    if not config.LOCAL_PDF_ROOT:
        raise HTTPException(404, "线上未部署 PDF，请通过 DOI 获取原文")
    root = Path(config.LOCAL_PDF_ROOT).resolve()
    for sub in sorted(p for p in root.iterdir() if p.is_dir()) + [root]:
        cand = (sub / file).resolve()
        # 防目录穿越：拼出来的路径必须仍在 root 之内
        if str(cand).startswith(str(root)) and cand.is_file():
            return FileResponse(cand, media_type="application/pdf")
    raise HTTPException(404, "本地未找到该 PDF")


# ==================== v2：起始页与学习页 ====================

@app.get("/api/overview")
def api_overview():
    """起始页数据：总量、年度曲线、人员/机构排行、国别分布、高被引。"""
    from . import analytics

    return analytics.overview()


@app.get("/api/benchmarks")
def api_benchmarks():
    """静电力性能指标，已做单位归一，每个点带实验条件与出处。"""
    from . import analytics

    return analytics.benchmarks()


@app.get("/api/tree")
def api_tree():
    """学习路径知识树的纯结构（不含检索查询词）。"""
    from . import knowledge_tree as kt

    return kt.skeleton()


class LearnReq(BaseModel):
    question: str
    per_node: int = 3


LOCATE_SYS = """你是静电驱动领域的学习路径规划器。用户提出一个问题，你要：
1. 从下面的知识树里挑出 2-4 个最该先学的节点，按学习先后排序（先基础后应用）；
2. 用 3-5 句话说明为什么按这个顺序学，每个节点解决什么问题。

只输出 JSON，不要解释：
{"nodes":["节点id","节点id"],"path":"学习顺序说明，中文，3-5句"}

节点 id 必须从下面这棵树里选，不能自己编：
"""


@app.post("/api/learn")
def learn(r: LearnReq):
    """问答 → 定位到知识树分支 → 把相关论文挂到分支上。"""
    from . import knowledge_tree as kt

    idx = _idx()

    def sse():
        def ev(t, d):
            return f"event: {t}\ndata: {json.dumps(d, ensure_ascii=False)}\n\n"

        try:
            focus, path_text = [], ""
            try:
                raw = llm.chat([{"role": "system", "content": LOCATE_SYS + kt.outline()},
                                {"role": "user", "content": r.question}],
                               temperature=0.1, max_tokens=500)
                js = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
                # 严格校验：模型编出来的节点 id 一律丢弃，宁可少也不能给假分支
                focus = [n for n in js.get("nodes", []) if kt.find(n)]
                path_text = js.get("path", "")
            except Exception as e:  # noqa: BLE001
                log.warning("学习路径定位失败，回退到关键词匹配：%s", e)

            if not focus:
                # 兜底：节点与问题的「召回重合度」。
                # 不能用 RRF 分求和 —— 那个分数全落在 0.016~0.03 的窄区间里，
                # 节点之间几乎没差别，任何先验一加就完全主导，结果是所有问题
                # 都返回同一组节点。改成：问题单独检索一次，再看每个节点的检索
                # 结果和它重合多少篇，重合度才是真有判别力的信号。
                qset = {h.file: i for i, h in
                        enumerate(idx.search(r.question, k_final=25))}
                if not qset:
                    # 问题本身一条都检索不到（典型场景：中文提问 + 向量路熔断）。
                    # 此时任何打分都是 0，排序结果只反映树的书写顺序，毫无意义。
                    # 与其给一个看着正常实则随机的路径，不如老实返回入门主线并说明。
                    yield ev("focus", {
                        "nodes": ["f_force", "m_induction", "a_robot"],
                        "path": "没能把这个问题匹配到具体分支 —— 检索没有召回任何内容。"
                                "若是中文提问，通常是向量检索不可用（API Key 或网络问题），"
                                "此时中文关键词检索必然零召回。下面给出的是通用入门主线。",
                    })
                    focus = ["f_force", "m_induction", "a_robot"]
                    for nid in focus:
                        node = kt.find(nid)
                        hits = idx.search(node.get("q", ""), k_final=r.per_node * 3,
                                          category=node.get("cat"))
                        seen, papers = set(), []
                        for h in hits:
                            if h.file in seen:
                                continue
                            seen.add(h.file)
                            papers.append({"file": h.file, "title": h.title, "year": h.year,
                                           "authors": (h.authors or "").split(",")[0],
                                           "venue": h.venue, "doi": h.doi, "cited": h.cited,
                                           "page": h.page, "category": h.category,
                                           "preview": h.preview})
                            if len(papers) >= r.per_node:
                                break
                        yield ev("node", {"id": nid, "label": node["label"], "en": node.get("en"),
                                          "desc": node.get("desc"), "level": node.get("level"),
                                          "papers": papers})
                    yield ev("done", {})
                    return
                beginner = any(w in r.question for w in
                               ("什么是", "入门", "没接触", "从哪", "新手", "初学", "零基础"))
                prior = {1: 1.35 if beginner else 1.0, 2: 1.0, 3: 0.75 if beginner else 1.0}
                scored = []
                for n in kt.leaves():
                    files = {h.file for h in idx.search(n.get("q", ""), k_final=25,
                                                        category=n.get("cat"))}
                    # 问题结果里排得越靠前的论文，重合时权重越高
                    s = sum(1.0 / (1 + qset[f]) for f in files if f in qset)
                    scored.append((s * prior.get(n.get("level", 2), 1.0),
                                   n.get("level", 2), n["id"]))
                scored.sort(key=lambda x: -x[0])
                # 选出来后按学习阶段重排，保证呈现顺序由浅入深
                focus = [i for _, _, i in sorted(scored[:3], key=lambda x: x[1])]
                path_text = "（模型未参与规划，以下按问题与各分支的文献重合度自动排序）"

            yield ev("focus", {"nodes": focus, "path": path_text})

            for nid in focus:
                node = kt.find(nid)
                if not node:
                    continue
                hits = idx.search(f"{node.get('q', '')} {r.question}",
                                  k_final=r.per_node * 3, category=node.get("cat"))
                papers, seen = [], set()
                for h in hits:
                    if h.file in seen:
                        continue
                    seen.add(h.file)
                    papers.append({"file": h.file, "title": h.title, "year": h.year,
                                   "authors": (h.authors or "").split(",")[0],
                                   "venue": h.venue, "doi": h.doi, "cited": h.cited,
                                   "page": h.page, "category": h.category,
                                   "preview": h.preview})
                    if len(papers) >= r.per_node:
                        break
                yield ev("node", {"id": nid, "label": node["label"], "en": node.get("en"),
                                  "desc": node.get("desc"), "level": node.get("level"),
                                  "papers": papers})
            yield ev("done", {})
        except Exception as e:  # noqa: BLE001
            log.exception("learn 失败")
            yield ev("error", {"msg": str(e)})

    return StreamingResponse(sse(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---- 页面路由。必须在 StaticFiles 挂载之前注册才能生效 ----
@app.get("/search")
def page_search():
    return FileResponse(STATIC / "search.html")


@app.get("/learn")
def page_learn():
    return FileResponse(STATIC / "learn.html")


@app.get("/healthz")
def healthz():
    return {"ok": True, "vectors": _idx().has_vectors}


if STATIC.exists():
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    # 本地调试用；线上由 Render 的 startCommand 带 $PORT 启动
    uvicorn.run("app.main:app", host="127.0.0.1", port=int(os.getenv("PORT", 8000)), reload=True)
