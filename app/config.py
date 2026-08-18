"""全局配置。所有密钥和可调参数集中在这里，代码里不出现硬编码。"""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# ---------- 路径 ----------
DATA_DIR = ROOT / "data"
DB_PATH = Path(os.getenv("DB_PATH", DATA_DIR / "library.db"))
VEC_PATH = Path(os.getenv("VEC_PATH", DATA_DIR / "vectors.npy"))
VEC_META_PATH = DATA_DIR / "vector_meta.json"
CKPT_PATH = DATA_DIR / ".vectors_ckpt.npz"  # 断点续传检查点，已 gitignore

# 本地 PDF 根目录。线上不设置（线上没有 PDF），本地设置后前端会多一个"打开本地 PDF"按钮
LOCAL_PDF_ROOT = os.getenv("LOCAL_PDF_ROOT", "")

# ---------- Embedding（固定走阿里云百炼，DeepSeek 不提供 embedding 接口）----------
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
# 默认公共 endpoint；若你的百炼账号要求业务空间隔离，改成
# https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding
DASHSCOPE_EMBED_URL = os.getenv(
    "DASHSCOPE_EMBED_URL",
    "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding",
)
EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-v4")
EMBED_DIM = int(os.getenv("EMBED_DIM", "1024"))
EMBED_BATCH = 10        # text-embedding-v3/v4 同步接口硬上限：每次 10 条
EMBED_MAX_CHARS = 6000  # 每条 ≤8192 token，按最坏情况 ~1.4 char/token 留足余量

# ---------- 对话模型（可切换）----------
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "deepseek")
PROVIDERS = {
    "deepseek": {
        "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
    },
    "qwen": {
        "base_url": os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        "api_key": DASHSCOPE_API_KEY,
        "model": os.getenv("QWEN_MODEL", "qwen-plus"),
    },
}

# ---------- 检索参数 ----------
K_KEYWORD = 30   # 关键词路召回条数
K_VECTOR = 30    # 向量路召回条数
K_FINAL = 8      # 融合后送给大模型的条数
RRF_K = 60       # RRF 平滑常数，业界惯例值
W_KEYWORD = 1.0  # 两路权重。术语精确匹配重要就调高关键词，概念检索重要就调高向量
W_VECTOR = 1.0

# ---------- 两大类 ----------
# 一级分类，由 scripts/recategorize.py 写入 papers.category
FM, EA = "film_motor", "electroadhesion"
CATEGORIES = {
    FM: {"label": "静电薄膜电机", "en": "Electrostatic Film Motor"},
    EA: {"label": "静电吸附 / 电粘附", "en": "Electroadhesion"},
}
# 原 ①②③④ 分级降为二级筛选，仍有价值（①核心是人工校过的高质量子集）
TIER_MAP = {"1": "①", "2": "②", "3": "③", "4": "④"}
