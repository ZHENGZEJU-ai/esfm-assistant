# 静电薄膜电机 / 静电吸附 · 科研知识助手

对 268 篇领域论文（6344 段全文）做**混合检索 + 带引用溯源的 RAG 问答**。
关键词路（SQLite FTS5 / BM25）与语义路（向量）用 RRF 融合，回答的每个论断都标注到具体论文和页码。

| | |
|---|---|
| 论文 / 段落 | 268 篇 · 6344 段 · 1981–2026 |
| 一级分类 | **film_motor** 静电薄膜电机 201 篇 · **electroadhesion** 静电吸附/电粘附 67 篇 |
| 二级分级 | ①核心·薄膜电机 / ②静电电机·机械 / ③电粘附·夹持 / ④外围（保留，可叠加筛选）|
| 检索 | FTS5 关键词 + 1024 维向量，RRF 融合 |
| Embedding | 阿里云百炼 `text-embedding-v4` |
| 对话模型 | DeepSeek / 通义千问，环境变量切换 |
| 部署 | FastAPI + 单页 HTML → Render |

---

## 快速开始

```bash
python -m venv .venv && .venv\Scripts\activate     # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                                # 填入 DASHSCOPE_API_KEY 和 DEEPSEEK_API_KEY

python scripts/selftest.py                          # 自检，不花钱，不需要 Key
python scripts/check_keys.py                        # 两个 Key 体检
python scripts/build_vectors.py --incremental --workers 4   # 只算新增段落

uvicorn app.main:app --reload                       # http://127.0.0.1:8000
```

**没跑 `build_vectors.py` 也能启动** —— 会自动降级成纯关键词检索，界面顶部会提示。

---

## 目录

```
app/
  config.py       全部可调参数和密钥读取
  embed.py        DashScope 向量化（走原生接口，因为只有它支持 text_type）
  retrieval.py    ★ 混合检索：FTS5 转义 + 向量 + 分类/分级过滤 + RRF 融合
  llm.py          provider 抽象（DeepSeek / 通义），流式输出
  prompts.py      系统提示词（强制引用溯源）
  main.py         FastAPI + SSE
  static/index.html
scripts/
  build_vectors.py  ★ 断点续传向量化（--incremental 只算新增）
  ingest_pdfs.py    PDF → 分段 → 入库（PyMuPDF 抽取，自动剥离出版商水印）
  recategorize.py   两大类判定 + 目录重组（元数据初分 + 模型复核存疑件）
  clean_boilerplate.py  清除已入库的 IEEE 下载水印
  check_keys.py     两个 API Key 体检
  make_eval.py      生成评测集骨架 + 自动提名候选 gold
  eval.py           ★ 检索质量评测：Recall@k / MRR / nDCG，支持配置对比
  selftest.py       自检：转义 / 召回 / RRF / 分类 / 降级
data/
  library.db        13 MB，入 Git
  vectors.npy       14 MB，入 Git（build_vectors.py 生成）
  vector_meta.json  行序 ↔ chunk rowid 映射
docs/             实施路线图、文献库溯源说明
legacy/ask.py     旧版命令行检索（已被 retrieval.py 取代，仅作参考）
PDFs/             .gitignore，不上云
  film_motor/       201 篇
  electroadhesion/  84 篇
```

---

## 两处关键设计

### 为什么不用向量数据库

6344 段 × 1024 维 float32 = **26 MB**。一个 numpy 数组 + 一次矩阵乘法，检索 < 1 ms。
上 Chroma/FAISS 只会增加依赖和部署复杂度，没有任何收益。这个判断连锁决定了：
不需要外部存储、不需要 Render 付费磁盘、512 MB 免费层绰绰有余。

**代价是 requirements.txt 必须保持干净** —— 装 torch / sentence-transformers / faiss 会直接 OOM。
embedding 走 API 正是为了避开这些重依赖。

### 为什么用 RRF 而不是加权分数相加

BM25 分数无上界、依赖语料统计；余弦相似度恒在 [-1,1]。直接线性组合需要精调归一化参数，
换个查询就失效。RRF 只看名次：

```
score(d) = Σ_路  weight / (60 + rank_路(d))
```

效果是「两路都排前面」的段落胜过「单路第一名」—— 这正是混合检索的意义。
`selftest.py` 第 4 项用一个最小例子验证了这个性质。

---

## 已知边界

- **中文关键词路必然零召回**。FTS5 的 unicode61 分词器不切中文，中文查询会被当成一个整词，
  匹配不上英文文献。这是设计上的已知行为，由向量路 + 查询扩写（`expand=true`，
  让模型先把中文问题转成英文术语）覆盖。`selftest.py` 里能看到这个现象。
- **19 篇 PDF 无法入库**：17 篇文件损坏（当年抓取时出版商返回 HTML 拦截页或下载截断），
  2 篇是扫描件需 OCR。清单见 `python scripts/ingest_pdfs.py --dry-run` 的输出，
  按 DOI 重新下载后跑 `ingest_pdfs.py` 即可补入。
- **交叉论文会同时出现在两个大类的筛选结果里**（设计如此，卡片上有「交叉」徽标）。
- **chunk 平均偏粗**。若发现回答抓不住重点，把 `ingest_pdfs.py` 的 `TARGET` 调到 800
  重新切分再重跑 embedding（成本 < 1 元）。
- **未完成的段落是零向量**，不会被检索命中，但也不报错。`vector_meta.json` 里的
  `completed` 字段会显示真实完成数。

---

## 部署到 Render

`render.yaml` 已配好，连上 GitHub 仓库即可。三个必须注意的点：

1. 启动命令必须用 `$PORT`，写死端口会报 Port scan timeout
2. 免费层 15 分钟无流量休眠，唤醒约 1 分钟；演示前先访问一次
3. 磁盘是临时的，数据只能来自 Git 仓库（本项目正是这么做的）

`DASHSCOPE_API_KEY` 和 `DEEPSEEK_API_KEY` 在 Render 面板 Environment 里手填（`sync: false`）。

**仓库建议设为 Private** —— 未上传 PDF，但数据库含出版商版权全文片段。

---

## API

| 端点 | 说明 |
|---|---|
| `GET /api/stats` | 库统计、当前检索模式、可用 provider |
| `POST /api/search` | 纯检索，不调大模型（调检索参数时用这个，不花钱） |
| `POST /api/ask` | RAG 问答，SSE 流式；先推 `sources` 事件再推 `token` |
| `GET /api/paper/{file}` | 单篇元数据 + 全部段落 |
| `GET /api/pdf/{file}` | 仅本地（需设 `LOCAL_PDF_ROOT`） |

检索类接口都支持 `category`（`film_motor` / `electroadhesion`）、`tier`、`year_min` / `year_max` 叠加筛选。

调参入口全在 `app/config.py`：`K_KEYWORD` / `K_VECTOR` / `K_FINAL` / `RRF_K` / `W_KEYWORD` / `W_VECTOR`。

---

## 评测（调参前先做这个）

改任何检索参数之前先建立基线，否则只是凭感觉。

```bash
python scripts/make_eval.py     # 生成 data/eval_set.json，20 题 + 自动提名候选
# ↑ 然后人工校对：把 gold_candidates 里真正能回答该问题的论文挪进 gold
python scripts/eval.py          # 总体分 + 分题型分
python scripts/eval.py --compare        # 关键词路 / 向量路 / 混合 对比
python scripts/eval.py --sweep-weights  # 扫 RRF 两路权重，给出最优值
python scripts/eval.py --no-expand      # 看中译英扩写到底值不值
```

20 题覆盖五种失败模式：`numeric` 数值型、`mechanism` 机理型、`compare` 对比型、
`zh2en` 中文检英文（关键词路必然零召回，纯考验向量路）、`history` 沿革型。
指标都在**论文级**上算 —— 同一篇的多个段落命中只算一次。

**标注是唯一需要你亲手做的部分。** 判据：这篇论文里确实有能回答该问题的内容，
而不是沾点边。宁可每题只留 2–3 篇最硬的，也别为凑数放宽 —— 评测集的价值全在标注质量。

详细路线图见 [`docs/实施路线图.md`](docs/实施路线图.md)。
