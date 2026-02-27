"""
agents/llm_factory.py
─────────────────────
统一的 LLM 实例工厂，根据 config.py 中的配置返回对应的 LLM 对象。
支持 OpenAI / Gemini / Ollama。
"""

import os
import sys

# 把项目根目录加到 sys.path（确保 config 能被正确导入）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    LLM_PROVIDER,
    LLM_MODEL,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    GOOGLE_API_KEY,
)


def get_llm(temperature: float = 0.7):
    """
    根据 LLM_PROVIDER 环境变量返回对应的 LLM 实例。

    Args:
        temperature: 生成温度（编剧/分镜用0.7创意温度，导演用0.3严格温度）
    """
    if LLM_PROVIDER == "openai":
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            raise ImportError("请安装 langchain-openai: pip install langchain-openai")

        return ChatOpenAI(
            model=LLM_MODEL,
            api_key=OPENAI_API_KEY or None,
            base_url=OPENAI_BASE_URL,
            temperature=temperature,
        )

    elif LLM_PROVIDER == "gemini":
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError:
            raise ImportError(
                "请安装 langchain-google-genai: pip install langchain-google-genai"
            )

        return ChatGoogleGenerativeAI(
            model=LLM_MODEL or "gemini-1.5-pro",
            google_api_key=GOOGLE_API_KEY or None,
            temperature=temperature,
        )

    elif LLM_PROVIDER == "ollama":
        try:
            from langchain_ollama import ChatOllama
        except ImportError:
            raise ImportError("请安装 langchain-ollama: pip install langchain-ollama")

        return ChatOllama(
            model=LLM_MODEL or "llama3.1",
            temperature=temperature,
        )

    else:
        raise ValueError(
            f"不支持的 LLM_PROVIDER: {LLM_PROVIDER}，请选择 openai / gemini / ollama"
        )
