"""
config.py (更新版)
──────────────────
新增：HUMAN_REVIEW, CHUNK_SIZE, CHUNK_OVERLAP 配置
"""

import os
from dotenv import load_dotenv

load_dotenv(override=True)

# ── LLM 配置 ──────────────────────────────────────────────────────────────────
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "siliconflow")

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("LLM_MODEL", "gpt-4o")

# SiliconFlow (硅基流动)
SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY", "")
SILICONFLOW_BASE_URL = os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
SILICONFLOW_MODEL = os.getenv("SILICONFLOW_MODEL", "deepseek-ai/DeepSeek-V3")

# Volcengine (火山引擎)
ARK_API_KEY = os.getenv("ARK_API_KEY", "")
ARK_LLM_MODEL = os.getenv("ARK_LLM_MODEL", "doubao-1-5-pro-32k-250115")

# Google
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# 根据 provider 选择正确的模型名（用于显示）
def _get_llm_model():
    provider = LLM_PROVIDER.lower()
    if provider == "siliconflow":
        return SILICONFLOW_MODEL
    elif provider == "volcengine":
        return ARK_LLM_MODEL
    else:
        return OPENAI_MODEL

LLM_MODEL = _get_llm_model()

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

# ── 图片风格配置（v3 新增）─────────────────────────────────────────────────────
# 支持的风格类型（使用中文）：
# - 真人电影风格: 真人电影演员风格（默认），严禁动漫/插画词汇
# - 动漫风格: 日系动画质感
# - 插画风格: 艺术手绘质感
# - 3D渲染风格: 游戏CG质感
IMAGE_STYLE_TYPE = os.getenv("IMAGE_STYLE_TYPE", "真人电影风格")

# 支持的图片风格类型（中文 key）
SUPPORTED_IMAGE_STYLES = {
    "真人电影风格": {
        "name": "真人电影风格",
        "description": "真人电影演员风格，严禁动漫/插画词汇",
    },
    "动漫风格": {
        "name": "动漫风格",
        "description": "日系动画质感，强调线条和色彩",
    },
    "插画风格": {
        "name": "插画风格",
        "description": "艺术手绘质感，强调绘画感",
    },
    "3D渲染风格": {
        "name": "3D渲染风格",
        "description": "游戏CG质感，强调立体感和光影",
    },
}

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
