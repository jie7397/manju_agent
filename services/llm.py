import os


class ArkLLMService:
    """LLM service for text generation - supports SiliconFlow, Volcengine Ark, OpenAI"""
    
    def __init__(self):
        self.provider = os.environ.get("LLM_PROVIDER", "siliconflow").lower()
        self.client = None
        self.model = None
        
        # 根据提供商初始化
        if self.provider == "siliconflow":
            self._init_siliconflow()
        elif self.provider == "volcengine":
            self._init_volcengine()
        else:
            self._init_openai()
    
    def _init_siliconflow(self):
        """初始化硅基流动 API"""
        self.api_key = os.environ.get("SILICONFLOW_API_KEY")
        self.base_url = os.environ.get("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
        self.model = os.environ.get("SILICONFLOW_MODEL", "deepseek-ai/DeepSeek-V3")
        
        if self.api_key:
            try:
                from openai import OpenAI
                self.client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=120.0)
                print(f"[LLM] SiliconFlow initialized: {self.model}")
            except ImportError:
                print("[Warning] openai not installed. LLM calls disabled.")
    
    def _init_volcengine(self):
        """初始化火山引擎 API"""
        self.api_key = os.environ.get("ARK_API_KEY")
        self.base_url = "https://ark.cn-beijing.volces.com/api/v3"
        self.model = os.environ.get("ARK_LLM_MODEL", "doubao-1-5-pro-32k-250115")
        
        if self.api_key:
            try:
                from openai import OpenAI
                self.client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=120.0)
                print(f"[LLM] Volcengine initialized: {self.model}")
            except ImportError:
                print("[Warning] openai not installed. LLM calls disabled.")
    
    def _init_openai(self):
        """初始化 OpenAI 兼容接口"""
        self.api_key = os.environ.get("OPENAI_API_KEY")
        self.base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.model = os.environ.get("LLM_MODEL", "gpt-4o")
        
        if self.api_key:
            try:
                from openai import OpenAI
                self.client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=120.0)
                print(f"[LLM] OpenAI initialized: {self.model}")
            except ImportError:
                print("[Warning] openai not installed. LLM calls disabled.")

    def generate_text(self, system_prompt: str, user_prompt: str, temperature: float = 0.7) -> str:
        """
        Generate text using LLM.
        """
        if not self.client:
            raise Exception(f"LLM client not initialized. Check {self.provider.upper()}_API_KEY setting.")

        print(f"[LLM] Generating text with {self.provider}/{self.model}...")
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
        )
        return response.choices[0].message.content.strip()