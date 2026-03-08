"""
agents/production_designer.py
──────────────────────────────
美术指导 Agent：负责场景提取和场景图片生成

v3 新增节点：
  - 从剧本中提取 1-2 个主场景
  - 为每个场景设计视觉风格和光影氛围
  - 生成场景设定图（scene_anchor）
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import SystemMessage, HumanMessage
from state import WorkflowState
from agents.llm_factory import get_llm
from agents.prompt_utils import render_prompt
from config import DEBUG, IMAGE_STYLE_TYPE, SUPPORTED_IMAGE_STYLES

# 图片生成服务
try:
    from services.image_gen import SeeddreamService
    from services.llm import ArkLLMService
    IMAGE_GEN_AVAILABLE = True
    LLM_SERVICE_AVAILABLE = True
except ImportError:
    IMAGE_GEN_AVAILABLE = False
    LLM_SERVICE_AVAILABLE = False


# 场景提取 Prompt
SCENE_EXTRACTOR_PROMPT = """# 美术指导任务

你是一位专业的电影美术指导，负责从剧本中提取场景并设计视觉风格。

## 输入
- 小说类型：{novel_type}
- 剧本内容：{screenplay_scenes}

## 任务
1. 提取 1-2 个主要场景（不要过多，保持简洁）
2. 为每个场景设计：
   - 场景名称
   - 场景描述（详细的环境细节）
   - 设计风格（如：minimalist, gothic, cyberpunk, ancient chinese）
   - 光影氛围（如：cinematic lighting, warm sunset, cold moonlight）
   - 色调关键词（用于 AI 绘画）

## 输出格式（JSON）
```json
{{
  "locations": [
    {{
      "location_id": "loc_001",
      "name": "场景名称",
      "description": "详细的环境描述",
      "design_style": "设计风格",
      "lighting_mood": "光影氛围",
      "color_keywords": "色调关键词（英文）"
    }}
  ]
}}
```

## 关键要求
- 场景数量：严格控制在 1-2 个
- 描述必须详细：包含材质、光影、氛围
- 风格必须明确：便于后续 AI 绘画
- 必须与剧情匹配：不要脱离剧本

请直接输出 JSON，不要有其他内容。
"""


def production_designer_node(state: WorkflowState) -> dict:
    """
    LangGraph 节点函数：美术指导 Agent
    
    从剧本中提取场景，生成场景设定图。
    """
    print("\n🎨 [美术指导 Agent] 开始设计场景...")

    screenplay_scenes = state.get("screenplay_scenes", [])
    if not screenplay_scenes:
        print("⚠️  [美术指导 Agent] 没有剧本数据，跳过场景设计")
        return {"scene_images": {}}

    # 构建 Prompt
    prompt = render_prompt(
        SCENE_EXTRACTOR_PROMPT,
        novel_type=state.get("novel_type", "仙侠/玄幻"),
        screenplay_scenes=json.dumps(screenplay_scenes, ensure_ascii=False, indent=2)
    )

    if DEBUG:
        print(f"[DEBUG] 美术指导 Prompt 长度: {len(prompt)} 字符")

    llm = get_llm(temperature=0.5)
    messages = [
        SystemMessage(content=prompt),
        HumanMessage(content="请提取场景并设计视觉风格，输出 JSON。"),
    ]

    response = llm.invoke(messages)
    raw_text = response.content

    if DEBUG:
        print(f"[DEBUG] 美术指导原始输出:\n{raw_text[:500]}")

    # 解析 JSON
    try:
        locations_data = _extract_json_from_response(raw_text)
        locations = locations_data.get("locations", [])
        print(f"✅ [美术指导 Agent] 完成！设计了 {len(locations)} 个场景")
    except ValueError as e:
        print(f"⚠️  [美术指导 Agent] JSON 解析失败: {e}")
        locations = []

    # v4: 图片生成移到 image_generator 节点，这里只提取场景信息
    # 将场景信息存储到 state 中，供后续 image_generator 使用
    scene_info = {}
    for loc in locations:
        lid = loc.get("location_id", "unknown")
        scene_info[lid] = {
            "name": loc.get("name", ""),
            "description": loc.get("description", ""),
            "design_style": loc.get("design_style", ""),
            "lighting_mood": loc.get("lighting_mood", "")
        }

    return {
        "scene_images": scene_info,  # 注意：这里存的是场景信息，不是生成的图片
    }


def _extract_json_from_response(text: str) -> dict:
    """从 LLM 响应中提取 JSON 对象"""
    import re

    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    pattern = r"```(?:json)?\s*([\s\S]+?)\s*```"
    match = re.search(pattern, text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"无法解析场景 JSON: {text[:200]}")


def _get_scene_style_system_prompt(style_type: str) -> str:
    """
    根据风格类型获取场景图片的 system_prompt（使用中文 key）
    """
    style_prompts = {
        "真人电影风格": (
            "你是一位世界级的电影制作设计师。"
            "请将场景描述转化为一段极具设计感、画面干净的大师级环境提示词。"
            "**核心要求：极简构图，电影确立镜头，画面必须干净大气，严禁杂乱。**"
            "**风格要求：必须将场景描述为【实地摄影】。严禁使用'概念图'、'插画'、'CG'等词汇。**"
            "**利用输入中的'设计风格'和'光影氛围'，强化场景的情绪表达。**"
            "重点描述场景的**真实物理材质**：石头的风化痕迹、木头的纹理、空气中的灰尘感。"
            "光影要求：使用自然光或电影级布光，强调真实感和层次感。"
            "**关键要求：输出必须是纯中文，禁止英文。**"
            "严禁包含人物角色，这是一个空镜。"
            "直接输出提示词内容，不要包含任何前缀。"
        ),
        "动漫风格": (
            "你是一位世界级的动漫美术设计师。"
            "请将场景描述转化为一段极具设计感的动漫风格环境提示词。"
            "**核心要求：日系动漫风格，强调线条感和色彩层次。**"
            "**风格要求：必须将场景描述为【动漫背景】。使用'动漫'、'动画'等词汇。**"
            "重点描述场景的**动漫特征**：清晰的线条、鲜明的色彩、有设计感的构图。"
            "光影要求：使用动漫风格的光照，强调氛围感。"
            "**关键要求：输出必须是纯中文，禁止英文。**"
            "严禁包含人物角色，这是一个空镜。"
            "直接输出提示词内容，不要包含任何前缀。"
        ),
        "插画风格": (
            "你是一位世界级的插画艺术家。"
            "请将场景描述转化为一段极具艺术感的插画风格环境提示词。"
            "**核心要求：艺术插画风格，强调手绘感和绘画质感。**"
            "**风格要求：必须将场景描述为【艺术插画】。使用'插画'、'手绘'等词汇。**"
            "重点描述场景的**插画特征**：艺术笔触、丰富的色彩层次、有设计感的构图。"
            "光影要求：使用艺术化的光照，强调氛围感和情绪表达。"
            "**关键要求：输出必须是纯中文，禁止英文。**"
            "严禁包含人物角色，这是一个空镜。"
            "直接输出提示词内容，不要包含任何前缀。"
        ),
        "3D渲染风格": (
            "你是一位世界级的游戏场景设计师。"
            "请将场景描述转化为一段极具立体感的3D渲染风格环境提示词。"
            "**核心要求：3D游戏场景风格，强调立体感和材质渲染。**"
            "**风格要求：必须将场景描述为【3D游戏场景】。使用'3D'、'游戏'、'CG'等词汇。**"
            "重点描述场景的**3D特征**：精细的建模、真实的材质渲染、次世代游戏画质。"
            "光影要求：使用游戏级的光照，强调体积光和环境光遮蔽。"
            "**关键要求：输出必须是纯中文，禁止英文。**"
            "严禁包含人物角色，这是一个空镜。"
            "直接输出提示词内容，不要包含任何前缀。"
        ),
    }
    return style_prompts.get(style_type, style_prompts["真人电影风格"])


def _get_scene_style_suffix(style_type: str) -> str:
    """
    根据风格类型获取追加的场景风格后缀（使用中文，适配 Seeddream 中文模型）
    增强场景的高级感和设计感
    """
    suffixes = {
        "真人电影风格": (
            "，写实摄影风格，真实照片，高细节，8k分辨率，35毫米胶片拍摄，电影级布光，极简构图，干净背景，电影确立镜头。"
            "场景要求：宏伟壮观的建筑结构、精致的装饰细节、华丽的材质纹理、考究的配色方案。"
            "细节要求：大理石光泽、金色镶边、精美的雕刻纹样、水晶吊灯、丝绸帷幔、名贵家具。"
            "氛围要求：奢华大气、皇家宫殿般高贵、奥斯卡最佳艺术指导奖水准、史诗级电影场景。"
            "光影要求：戏剧性的光影对比、丁达尔效应、体积光、金色阳光穿透、电影级调色。"
        ),
        "动漫风格": (
            "，动漫风格背景，高质量动漫，精细动漫环境，鲜艳色彩，4k分辨率，吉卜力风格。"
            "场景要求：梦幻般的建筑、华丽的城堡、精致的花园、魔法般的光效。"
            "细节要求：闪闪发光的水晶、飘浮的魔法粒子、彩虹般的光晕、梦幻的云彩。"
            "氛围要求：童话般唯美、新海诚级别背景、顶级动漫电影场景。"
        ),
        "插画风格": (
            "，数字插画，艺术站热门，高细节插画，概念艺术，绘画风格，环境艺术。"
            "场景要求：史诗级的场景设计、华丽的建筑细节、丰富的装饰元素。"
            "细节要求：金色的光晕、神秘的粒子效果、精致的花纹装饰、艺术化的光影。"
            "氛围要求：史诗级概念艺术、顶级游戏原画、艺术站首页推荐品质。"
        ),
        "3D渲染风格": (
            "，3D渲染，虚幻引擎5，Octane渲染，高细节3D环境，次世代画质，光线追踪，游戏场景。"
            "场景要求：次世代场景建模、PBR高级材质、精细的几何细节、真实的物理渲染。"
            "细节要求：金属反射、玻璃折射、石材纹理、布料模拟、粒子系统、体积雾。"
            "氛围要求：3A游戏大作水准、次世代场景设计、顶级CG品质、电影级视觉特效。"
        ),
    }
    return suffixes.get(style_type, suffixes["真人电影风格"])


def _refine_scene_prompt_with_llm(location: dict, llm_service, style_tags: list, style_type: str = None) -> str:
    """
    使用 LLM 精修场景图片提示词（强制使用 LLM，不回退）
    
    Args:
        location: 场景信息
        llm_service: LLM 服务实例
        style_tags: 风格标签列表
        style_type: 风格类型，默认使用配置中的 IMAGE_STYLE_TYPE
    
    Returns:
        精修后的提示词
    
    Raises:
        RuntimeError: 当 LLM 服务不可用或精修失败时抛出
    """
    if style_type is None:
        style_type = IMAGE_STYLE_TYPE
    
    if not llm_service or not llm_service.client:
        raise RuntimeError(
            f"LLM 服务不可用，无法生成场景 '{location.get('name', 'Unknown')}' 的图片提示词。"
            "请确保 ARK_API_KEY 已配置且 LLM 服务正常运行。"
        )
    
    system_prompt = _get_scene_style_system_prompt(style_type)
    
    loc_name = location.get("name", "Unknown")
    user_prompt = f"场景名称: {loc_name}。描述: {location.get('description', '')}。风格: {', '.join(style_tags)}。"
    
    try:
        refined = llm_service.generate_text(system_prompt, user_prompt)
        if not refined:
            raise RuntimeError(f"LLM 返回空提示词，场景: {loc_name}")
        return refined
    except Exception as e:
        raise RuntimeError(f"LLM 场景提示词精修失败，场景 '{loc_name}': {e}")


def _build_scene_image_prompt(location: dict) -> str:
    """
    构建场景图片生成 Prompt（基础版本，作为 fallback）
    """
    name = location.get("name", "Unknown Location")
    description = location.get("description", "")
    design_style = location.get("design_style", "cinematic")
    lighting_mood = location.get("lighting_mood", "cinematic lighting")
    color_keywords = location.get("color_keywords", "")

    prompt = (
        f"{name}, {description}. "
        f"Design style: {design_style}. "
        f"Lighting: {lighting_mood}. "
        f"Color palette: {color_keywords}. "
        f"photorealistic, raw photo, highly detailed, 8k, "
        f"cinematic establishing shot, wide angle, "
        f"shot on 35mm film, film grain. "
        f"No characters, empty scene."
    )

    return prompt