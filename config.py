"""
config.py (更新版)
──────────────────
新增：HUMAN_REVIEW, CHUNK_SIZE, CHUNK_OVERLAP 配置
"""

import os

# ── LLM 配置 ──────────────────────────────────────────────────────────────────
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# ── 工作流控制 ────────────────────────────────────────────────────────────────
MAX_REVISIONS = int(os.getenv("MAX_REVISIONS", "3"))

# ── 人工审核开关（v2 新增） ────────────────────────────────────────────────────
# 设为 true 时，音效师完成后会暂停并展示预览，等待用户确认
# 设为 false（默认）时，全自动流程
HUMAN_REVIEW = os.getenv("HUMAN_REVIEW", "false").lower() == "true"

# ── 长文本分段（v2 新增） ─────────────────────────────────────────────────────
# 超过 CHUNK_SIZE 字符的文本会自动分段处理
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "2000"))
# 相邻分段之间的重叠字符数（保留上下文连贯性）
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))

# ── 调试模式 ──────────────────────────────────────────────────────────────────
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# ── 支持的小说类型 ─────────────────────────────────────────────────────────────
SUPPORTED_NOVEL_TYPES = [
    "仙侠/玄幻",
    "都市/现代",
    "赛博朋克/科幻",
    "古代言情",
    "武侠",
    "末世/灾难",
    "校园/青春",
    "历史",
]
