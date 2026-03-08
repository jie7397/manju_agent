import os
import base64
import requests
from typing import Optional, Union, List


class PipelineError(Exception):
    """Custom exception for pipeline errors"""
    pass


def ensure_parent(path: str):
    """Ensure parent directory exists"""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


class SeeddreamService:
    def __init__(self, model: Optional[str] = None):
        api_key = os.environ.get("ARK_API_KEY")
        base_url = "https://ark.cn-beijing.volces.com/api/v3"
        
        self.api_key = api_key
        self.client = None
        if api_key:
            try:
                from volcenginesdkarkruntime import Ark
                self.client = Ark(base_url=base_url, api_key=api_key, timeout=600.0)
            except ImportError:
                print("[Warning] volcenginesdkarkruntime not installed. Image generation disabled.")
        
        self.model = model or os.environ.get("ARK_IMAGE_MODEL") or "doubao-seedream-5-0-260128"
        print(f"[Seeddream] Using model: {self.model}")

    def _encode_image_to_base64(self, image_path: str) -> str:
        with open(image_path, "rb") as image_file:
            data = image_file.read()
            size_mb = len(data) / (1024 * 1024)
            print(f"[Seeddream] Encoding image ({size_mb:.2f} MB)...")
            return base64.b64encode(data).decode('utf-8')

    def generate_image(self, prompt: str, output_path: str, size: str = "2K", reference_image_path: Union[str, List[str], None] = None) -> str:
        """
        Generate image using Seeddream API.
        """
        if not self.client:
            raise PipelineError("ARK_API_KEY not set or SDK not installed.")

        print(f"[Seeddream] Generating image for prompt: {prompt[:50]}...")
        
        kwargs = {
            "model": self.model,
            "prompt": prompt,
            "size": size,
            "response_format": "url",
        }
        
        image_inputs = []
        if reference_image_path:
            paths = [reference_image_path] if isinstance(reference_image_path, str) else reference_image_path
            
            for p in paths:
                if p and os.path.exists(p):
                    try:
                        print(f"[Seeddream] Encoding reference image: {p}")
                        b64 = self._encode_image_to_base64(p)
                        image_inputs.append(f"data:image/png;base64,{b64}")
                    except Exception as e:
                        print(f"[Warning] Failed to encode reference image {p}: {e}")

        if image_inputs:
            kwargs["image"] = image_inputs if len(image_inputs) > 1 else image_inputs[0]
            if len(image_inputs) > 1:
                kwargs["sequential_image_generation"] = "disabled"

        try:
            response = self.client.images.generate(**kwargs)
        except TypeError:
            std_params = ["model", "prompt", "size", "response_format", "n", "quality", "style", "user"]
            new_params = {k: v for k, v in kwargs.items() if k in std_params}
            new_extra = {k: v for k, v in kwargs.items() if k not in std_params}
            response = self.client.images.generate(**new_params, extra_body=new_extra)

        if not response.data or not response.data[0].url:
            raise PipelineError("Seeddream API returned no image URL.")

        image_url = response.data[0].url
        self._download_image(image_url, output_path)
        return output_path

    def _download_image(self, url: str, path: str) -> None:
        try:
            print(f"[Seeddream] Downloading image to {path}...")
            resp = requests.get(url, stream=True, timeout=30)
            resp.raise_for_status()
            
            ensure_parent(path)
            with open(path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
        except Exception as e:
            raise PipelineError(f"Failed to download image from {url}: {str(e)}")