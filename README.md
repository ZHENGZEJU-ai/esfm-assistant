# 静电薄膜电机 · 科研知识助手

v0.3.0：网站仅提供 **film-motor 静电薄膜电机**。首页直接展示领域概览，保留全文检索、带页码引用的 RAG 问答和学习路径。

当前网站索引范围：199 篇论文、3,671 段全文。关键词检索使用 SQLite FTS5，语义检索使用百炼 `text-embedding-v4`，两路以 RRF 融合；对话模型支持 DeepSeek / 通义千问。

## 本地启动

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 在 .env 配置已有 API Key
python scripts/selftest.py
python -m unittest discover -s tests -v
uvicorn app.main:app --reload
```

`selftest.py` 与回归测试不调用收费 API。运行服务后访问 http://127.0.0.1:8000。

## 页面与接口

| 地址 | 用途 |
|---|---|
| `/`、`/fm` | 静电薄膜电机概览：性能、研究人员、地域、高被引论文 |
| `/fm/search` | 全文检索、问答、引用溯源 |
| `/fm/learn` | 薄膜电机知识树与学习路径 |
| `/api/stats` | 当前可检索范围统计 |
| `/api/overview`、`/api/benchmarks` | 电机领域统计、实测性能数据 |
| `/api/tree`、`/api/learn` | 电机知识树、流式学习路径 |
| `/api/search`、`/api/ask` | 检索、流式问答 |
| `/api/paper/{file}` | 电机论文及段落 |
| `/api/pdf/{file}` | 本地 PDF（需配置 `LOCAL_PDF_ROOT`） |
| `/healthz` | 健康状态、版本和领域 |

旧 `/all`、`/search`、`/learn`、`/all/search`、`/all/learn` 地址重定向到对应电机页面。`/ea` 及其子页返回 404。

所有检索默认仅包含 `papers.category = 'film_motor'`，包括省略分类或传 `null` 的请求。交叉标记不会将其他主分类论文纳入。显式请求其他分类返回校验错误；统计、论文详情、PDF 和学习接口采用相同范围。

## 项目结构

- `app/`：FastAPI 服务、检索、模型调用、统计、知识树和静态页面。
- `scripts/`：离线入库、分类、向量构建、元数据抽取和评测工具。
- `tests/`：领域隔离与接口回归测试。
- `data/`：历史原始数据库、向量与文献目录；网站在读取时限定为 film_motor，不改写原始资料。
- `docs/`：使用说明及历史建库记录。
- `PDFS/`：本地全文，Git 忽略，线上通过 DOI 获取原文。
- `render.yaml`：既有 Render Web Service 配置。

本次是网站领域收敛更新，保留已有索引及向量映射。此前在本地合并整理的 PDF/Excel 不会因放入文件夹自动变成网站索引；新文献需完成元数据对应、全文入库和向量更新后另行发布。

## 数据维护

离线工具依赖见 `requirements-dev.txt`。原有 `recategorize.py` 和目录文件用于历史资料分类；网站只开放主分类为 film_motor 的记录。不要把目录条目数或磁盘 PDF 数当作可检索论文数。

新增或重命名 PDF 后先核对文件名、DOI、数据库记录，避免重复入库；更新段落后同步向量及 `vector_meta.json`。纯新增段落可用：

```bash
python scripts/build_vectors.py --incremental --workers 4
```

若已有段落正文被修改，应重新计算对应向量，不能仅依赖 rowid 复用。

性能图只显示推力密度、推力、速度和效率；每个点保留实验条件和出处。地域覆盖率只计入当前电机论文。被引数是历史采集值，并非实时更新。

## Render 部署

既有服务连接 GitHub `main` 分支，使用 `render.yaml` 声明的构建与启动命令。密钥在 Render Environment 中配置，不提交 `.env`。

```text
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

推送后在 Render 确认对应提交部署成功，并检查 `/healthz` 返回版本 `0.3.0`、领域 `film_motor`。数据库与向量随仓库部署；PDF 和本地工作输出不上传。

## 已知边界

中文关键词检索对英文正文的召回有限，需语义检索和中译英扩写支持。模型或向量服务不可用时，系统尽量降级到关键词检索。PDF 抽取可能使公式、表格变形；引用页码按 PDF 页序核对。评测集尚未人工标注 gold，不能据此声称检索质量分数。
