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


@app.get("/healthz")
def healthz():
    return {"ok": True, "vectors": _idx().has_vectors}


if STATIC.exists():
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    # 本地调试用；线上由 Render 的 startCommand 带 $PORT 启动
    uvicorn.run("app.main:app", host="127.0.0.1", port=int(os.getenv("PORT", 8000)), reload=True)
