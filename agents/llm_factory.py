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

import config

def get_llm(temperature: float = 0.7):
    """
    根据 LLM_PROVIDER 环境变量/配置返回对应的 LLM 实例。

    Args:
        temperature: 生成温度（编剧/分镜用0.7创意温度，导演用0.3严格温度）
    """
    # 动态获取当前配置/环境变量
    llm_provider = os.getenv("LLM_PROVIDER", getattr(config, "LLM_PROVIDER", "openai"))
    llm_model = os.getenv("LLM_MODEL", getattr(config, "LLM_MODEL", ""))

    if llm_provider == "openai":
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            raise ImportError("请安装 langchain-openai: pip install langchain-openai")

        api_key = getattr(config, "OPENAI_API_KEY", "") or os.getenv("OPENAI_API_KEY", "")
        base_url = getattr(config, "OPENAI_BASE_URL", "https://api.openai.com/v1") or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

        return ChatOpenAI(
            model=llm_model or "gpt-4o",
            api_key=api_key or None,
            base_url=base_url,
            temperature=temperature,
        )

    elif llm_provider == "gemini":
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError:
            raise ImportError(
                "请安装 langchain-google-genai: pip install langchain-google-genai"
            )

        api_key = getattr(config, "GOOGLE_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")

        return ChatGoogleGenerativeAI(
            model=llm_model or "gemini-2.5-flash",
            google_api_key=api_key or None,
            temperature=temperature,
        )

    elif llm_provider == "ollama":
        try:
            from langchain_ollama import ChatOllama
        except ImportError:
            raise ImportError("请安装 langchain-ollama: pip install langchain-ollama")

        return ChatOllama(
            model=llm_model or "llama3.1",
            temperature=temperature,
        )

    else:
        raise ValueError(
            f"不支持的 LLM_PROVIDER: {LLM_PROVIDER}，请选择 openai / gemini / ollama"
        )
