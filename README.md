# 静电薄膜电机 · 科研知识助手

v0.4.0：网站仅提供 **film-motor 静电薄膜电机**。首页直接展示领域概览，保留全文检索、带页码引用的 RAG 问答和学习路径。

当前网站索引范围与精选论文库完全同步：**82 篇论文**（`PDFs/film_motor/`，编号 `0001`–`0082`，主表见 `论文库_第三列评价W.xlsx`）、**2,071 段检索文本**（含 3 篇扫描件的来源摘要），并已集成 `论文库_第三列评价W.xlsx` 第三列的人工**论文评价**（在问答结果引用后及每张文献卡片中直接展示）。关键词检索使用 SQLite FTS5，语义检索使用百炼 `text-embedding-v4`，两路以 RRF 融合；对话模型支持 DeepSeek / 通义千问。

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
| `/fm/search` | 全文检索、问答、引用溯源与引用论文评价（来源：`论文库_第三列评价W.xlsx`） |
| `/fm/learn` | 薄膜电机知识树与学习路径 |
| `/api/stats` | 当前可检索范围统计 |
| `/api/overview`、`/api/benchmarks` | 电机领域统计、实测性能数据 |
| `/api/tree`、`/api/learn` | 电机知识树、流式学习路径 |
| `/api/search`、`/api/ask` | 检索、流式问答 |
| `/api/paper/{file}` | 电机论文及段落（含 `evaluation` 论文评价） |
| `/api/pdf/{file}` | 本地 PDF（需配置 `LOCAL_PDF_ROOT`） |
| `/healthz` | 健康状态、版本和领域 |

旧 `/all`、`/search`、`/learn`、`/all/search`、`/all/learn` 地址重定向到对应电机页面。`/ea` 及其子页返回 404。

所有检索默认仅包含 `papers.category = 'film_motor'`，包括省略分类或传 `null` 的请求。交叉标记不会将其他主分类论文纳入。显式请求其他分类返回校验错误；统计、论文详情、PDF 和学习接口采用相同范围。

## 项目结构

- `app/`：FastAPI 服务、检索、模型调用、统计、知识树和静态页面。
- `scripts/`：离线入库、分类、向量构建、元数据抽取和评测工具。
- `tests/`：领域隔离与接口回归测试。
- `data/`：当前静电电机数据库（82 篇 / 2,071 段）、向量、导入清单，以及历史文献目录。
- `docs/`：使用说明及历史建库记录。
- `PDFs/film_motor/`：当前已纳入 Git 追踪，包含去重重编号后的 82 篇静电薄膜电机 PDF（`0001`–`0082`）及最新主表 `论文库_第三列评价W.xlsx`；`PDFs/` 下其余历史目录与压缩包继续由 `.gitignore` 忽略。
- `render.yaml`：既有 Render Web Service 配置。

2026-11-11 精选论文库与网站索引全面同步：
- 在前期合并筛选的基础上，去除会议与期刊重复、跨语言重复及已剔除条目，将 `PDFs/film_motor/` 内剩余的 **82 篇 PDF** 重新连续编号为 `0001`–`0082`，并同步更新主表 `PDFs/film_motor/论文库_第三列评价W.xlsx`。
- 网站检索数据库（`data/library.db`、`data/vectors.npy`、`data/categories.json`、`data/import_manifest.json`）已同步重构为这 **82 篇论文、2,071 段检索文本**（其中 3 篇扫描件仅索引来源摘要并明确标注；编号 `0011`、`0048` 的复用全文来自同篇归档版本，已注明页码对应归档版本）。
- 同步导入 `论文库_第三列评价W.xlsx` 第三列“评价”（共 27 篇带有详细人工批注评价），在 `/fm/search` 问答回答下方新增“**引用论文评价**”汇总板块，并在每条文献引用卡片、大模型问答提示词及 `/fm/learn` 学习路径卡片中同步展示。

本地完整归档与其余子目录不上传。仓库中 `catalog_all.xlsx` 和 `catalog_film_motor.xlsx` 为历史目录，不是当前主表；最新主表为仓库中的 `PDFs/film_motor/论文库_第三列评价W.xlsx`。

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

推送后在 Render 确认对应提交部署成功，并检查 `/healthz` 返回版本 `0.4.0`、领域 `film_motor`。数据库、向量与 `PDFs/film_motor/` 随仓库同步；其余 `PDFs/` 子目录和本地工作输出不上传。

## 已知边界

中文关键词检索对英文正文的召回有限，需语义检索和中译英扩写支持。模型或向量服务不可用时，系统尽量降级到关键词检索。PDF 抽取可能使公式、表格变形；引用页码按 PDF 页序核对。评测集尚未人工标注 gold，不能据此声称检索质量分数。
