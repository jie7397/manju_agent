"""
agents/character_extractor.py
──────────────────────────────
角色提取 Agent：工作流的第一个节点，从原始网文中提取所有角色档案
和世界观视觉风格，供后续分镜师使用，保证全剧视觉一致性。

v3 更新：
  - 增加年龄（age）、种族（ethnicity）提取
  - 增加写实风格标签注入
  - 增加图片生成（anchor_sheet）
"""

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import SystemMessage, HumanMessage
from state import WorkflowState, CharacterSheet, CharacterProfile
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


_PROMPT_PATH = (
    Path(__file__).parent.parent / "prompts" / "character_extractor_prompt.md"
)
_PROMPT_TEMPLATE = _PROMPT_PATH.read_text(encoding="utf-8")

# 默认写实风格标签
DEFAULT_STYLE_TAGS = [
    "photorealistic",
    "raw photo", 
    "highly detailed skin texture",
    "8k",
    "film grain",
    "cinematic lighting",
    "shot on 35mm film"
]

DEFAULT_NEGATIVE_TAGS = [
    "anime",
    "cartoon",
    "illustration",
    "drawing",
    "painting",
    "3d render",
    "cgi",
    "digital art",
    "low quality",
    "bad anatomy",
    "distorted face"
]


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
    raise ValueError(f"无法解析角色档案 JSON: {text[:200]}")


def character_extractor_node(state: WorkflowState) -> dict:
    """
    LangGraph 节点函数：角色提取 Agent

    输出 state['character_sheet']，包含所有角色档案和世界观色调。
    v3 新增：生成角色设定图（anchor_sheet）。
    """
    print("\n📚 [角色提取 Agent] 开始分析角色...")

    prompt = render_prompt(
        _PROMPT_TEMPLATE,
        novel_type=state.get("novel_type", "仙侠/玄幻"),
        novel_text=state["novel_text"],
    )

    if DEBUG:
        print(f"[DEBUG] 角色提取 Prompt 长度: {len(prompt)} 字符")

    # 角色提取需要精确，temperature 较低
    llm = get_llm(temperature=0.3)
    messages = [
        SystemMessage(content=prompt),
        HumanMessage(content="请分析原文，输出角色档案库 JSON。"),
    ]

    response = llm.invoke(messages)
    raw_text = response.content

    if DEBUG:
        print(f"[DEBUG] 角色提取原始输出:\n{raw_text[:800]}")

    try:
        sheet: CharacterSheet = _extract_json_from_response(raw_text)
        chars = sheet.get("main_characters", [])
        
        # v3: 为每个角色补充年龄、种族、风格标签
        for char in chars:
            _enhance_character_with_visual_info(char, state.get("novel_type", ""))
        
        print(
            f"✅ [角色提取 Agent] 完成！识别到 {len(chars)} 个角色：",
            "、".join(c.get("name", "?") for c in chars),
        )
        
        # v4: 图片生成移到 image_generator 节点，这里只提取角色档案
        return {
            "character_sheet": sheet,
        }
    except ValueError as e:
        print(f"⚠️  [角色提取 Agent] 解析失败（{e}），使用空档案继续")
        return {
            "character_sheet": {
                "main_characters": [],
                "world_visual_style": "未能自动提取，请参考原文",
                "color_palette": "",
            },
            "character_images": {},
            "image_prompts": {}
        }


def _enhance_character_with_visual_info(char: CharacterProfile, novel_type: str):
    """
    为角色补充视觉信息：年龄、种族、风格标签
    """
    # 确保有 style_tags
    if "style_tags" not in char:
        char["style_tags"] = DEFAULT_STYLE_TAGS.copy()
    else:
        # 合并默认标签
        char["style_tags"] = list(set(char["style_tags"] + DEFAULT_STYLE_TAGS))
    
    # 确保有 negative_tags
    if "negative_tags" not in char:
        char["negative_tags"] = DEFAULT_NEGATIVE_TAGS.copy()
    
    # 如果没有 age，尝试从描述中推断
    if "age" not in char or not char["age"]:
        appearance = char.get("appearance", "")
        if "少年" in appearance or "少女" in appearance:
            char["age"] = "16-18 years old"
        elif "中年" in appearance or "中年" in char.get("description", ""):
            char["age"] = "40-50 years old"
        elif "老" in appearance or "老者" in appearance:
            char["age"] = "60-70 years old"
        else:
            char["age"] = "20-30 years old"  # 默认青年
    
    # 如果没有 ethnicity，根据小说类型推断
    if "ethnicity" not in char or not char["ethnicity"]:
        if "仙侠" in novel_type or "玄幻" in novel_type or "古" in novel_type:
            char["ethnicity"] = "Chinese, East Asian"
        else:
            char["ethnicity"] = "East Asian"


def _get_character_style_system_prompt(style_type: str) -> str:
    """
    根据风格类型获取角色图片的 system_prompt（使用中文 key）
    增强服装高级感的描述
    """
    style_prompts = {
        "真人电影风格": (
            "你是一位精通 AI 绘画（Seeddream 模型）的提示词专家。"
            "**绝对要求：输出必须是纯中文，禁止使用任何英文单词！**"
            "请将角色描述转化为一段详细的中文绘画提示词。"
            "**核心要求：必须将角色描述为真人电影演员。严禁使用任何'插画'、'动漫'、'二次元'、'CG'等词汇。**"
            "**关键要求：必须根据提供的种族和年龄描述，准确转化为面部特征。**"
            "**如果种族是'Chinese'或'East Asian'，必须描述为：典型的东方面孔、黑发、深褐色眼睛、五官柔和。严禁生成深邃眼窝或高耸鼻梁等西方特征。**"
            "重点描述角色的真实生理特征：皮肤纹理、毛孔、皱纹、发丝质感、眼神光。"
            "**服装高级感要求：服装必须有设计感，严禁素色单调！**"
            "- 必须描述精致的刺绣纹样、华丽的滚边镶边、考究的配色搭配"
            "- 必须描述服装材质细节：丝绸光泽、天鹅绒质感、金银丝线装饰、珠宝配饰点缀"
            "- 必须指定明确的服装主色调和配色方案（例如：深蓝色长袍配金色滚边、银色刺绣）"
            "- 服装整体气质要奢华大气、贵族风范、奥斯卡最佳服装设计奖水准"
            "光影要求：使用中性、柔和、均匀的平光演播室照明，以便后续合成。"
            "**再次强调：输出必须是纯中文，禁止英文！服装必须有设计感和高级感！**"
            "直接输出提示词内容，不要包含任何前缀或解释。"
        ),
        "动漫风格": (
            "你是一位精通 AI 绘画（Seeddream 模型）的提示词专家。"
            "**绝对要求：输出必须是纯中文，禁止使用任何英文单词！**"
            "请将角色描述转化为一段详细的中文绘画提示词。"
            "**核心要求：必须将角色描述为日系动漫角色。强调线条感、大眼睛、夸张的表情。**"
            "**关键要求：必须根据提供的种族和年龄描述，准确转化为动漫风格的面部特征。**"
            "重点描述角色的动漫特征：大眼睛、尖下巴、柔和的线条、鲜艳的发色。"
            "**服装高级感要求：服装必须有设计感，严禁素色单调！**"
            "- 必须描述华丽的服装设计、精致的蕾丝花边、飘逸的丝绸质感"
            "- 必须描述闪亮的宝石装饰、流动的光效、梦幻的渐变配色"
            "- 必须指定明确的服装主色调和配色方案"
            "- 服装整体气质要梦幻唯美、公主王子般高贵、顶级动漫制作水准"
            "光影要求：使用柔和的动漫风格光照，强调轮廓光。"
            "**再次强调：输出必须是纯中文，禁止英文！服装必须有设计感和高级感！**"
            "直接输出提示词内容，不要包含任何前缀或解释。"
        ),
        "插画风格": (
            "你是一位精通 AI 绘画（Seeddream 模型）的提示词专家。"
            "**绝对要求：输出必须是纯中文，禁止使用任何英文单词！**"
            "请将角色描述转化为一段详细的中文绘画提示词。"
            "**核心要求：必须将角色描述为艺术插画角色。强调手绘感、艺术质感。**"
            "**关键要求：必须根据提供的种族和年龄描述，准确转化为插画风格的面部特征。**"
            "重点描述角色的插画特征：手绘线条、艺术笔触、丰富的色彩层次。"
            "**服装高级感要求：服装必须有设计感，严禁素色单调！**"
            "- 必须描述艺术化的服装设计、丰富的装饰纹样、华丽的配色方案"
            "- 必须描述金色描边、宝石点缀、流动的光影、梦幻的粒子效果"
            "- 必须指定明确的服装主色调和配色方案"
            "- 服装整体气质要史诗级概念艺术、顶级游戏原画水准"
            "光影要求：使用艺术化的光照，强调氛围感和情绪表达。"
            "**再次强调：输出必须是纯中文，禁止英文！服装必须有设计感和高级感！**"
            "直接输出提示词内容，不要包含任何前缀或解释。"
        ),
        "3D渲染风格": (
            "你是一位精通 AI 绘画（Seeddream 模型）的提示词专家。"
            "**绝对要求：输出必须是纯中文，禁止使用任何英文单词！**"
            "请将角色描述转化为一段详细的中文绘画提示词。"
            "**核心要求：必须将角色描述为3D游戏角色。强调立体感、材质渲染、游戏CG质感。**"
            "**关键要求：必须根据提供的种族和年龄描述，准确转化为3D风格的面部特征。**"
            "重点描述角色的3D特征：精细的建模、真实的材质渲染、次世代游戏画质。"
            "**服装高级感要求：服装必须有设计感，严禁素色单调！**"
            "- 必须描述次世代服装建模、PBR高级材质、精细的法线贴图"
            "- 必须描述金属扣环的光泽反射、皮革的质感、丝绸的流动感、珠宝的折射效果"
            "- 必须指定明确的服装主色调和配色方案"
            "- 服装整体气质要3A游戏大作水准、次世代角色设计、顶级CG品质"
            "光影要求：使用游戏级的光照，强调体积光和环境光遮蔽。"
            "**再次强调：输出必须是纯中文，禁止英文！服装必须有设计感和高级感！**"
            "直接输出提示词内容，不要包含任何前缀或解释。"
        ),
    }
    return style_prompts.get(style_type, style_prompts["真人电影风格"])


def _get_style_suffix(style_type: str) -> str:
    """
    根据风格类型获取追加的风格后缀（使用中文，适配 Seeddream 中文模型）
    增强服装和场景的高级感
    """
    suffixes = {
        "真人电影风格": (
            "，写实摄影风格，真实照片，高细节皮肤纹理，8k分辨率，35毫米胶片拍摄，电影级布光。"
            "服装要求：精致的刺绣纹样、华丽的滚边镶边、细腻的布料褶皱、考究的配色搭配、高级定制质感。"
            "细节要求：金银丝线装饰、珠宝配饰点缀、丝绸光泽、天鹅绒质感、皮革纹理。"
            "整体气质：奢华大气、贵族风范、电影级服装设计、奥斯卡最佳服装设计奖水准。"
        ),
        "动漫风格": (
            "，动漫风格，高质量动漫，精细动漫面部，鲜艳色彩，4k分辨率，吉卜力风格。"
            "服装要求：华丽的服装设计、精致的蕾丝花边、飘逸的丝绸质感、梦幻的渐变配色。"
            "细节要求：闪亮的宝石装饰、流动的光效、魔法粒子环绕、精致的发饰配饰。"
            "整体气质：梦幻唯美、公主王子般高贵、顶级动漫制作水准。"
        ),
        "插画风格": (
            "，数字插画，艺术站热门，高细节插画，概念艺术，绘画风格。"
            "服装要求：艺术化的服装设计、丰富的装饰纹样、华丽的配色方案、精致的细节刻画。"
            "细节要求：金色描边、宝石点缀、流动的光影、梦幻的粒子效果。"
            "整体气质：史诗级概念艺术、顶级游戏原画水准、艺术站首页推荐品质。"
        ),
        "3D渲染风格": (
            "，3D渲染，虚幻引擎5，Octane渲染，高细节3D模型，次世代画质，光线追踪。"
            "服装要求：次世代服装建模、PBR高级材质、精细的法线贴图、真实的布料模拟。"
            "细节要求：金属扣环的光泽反射、皮革的磨损痕迹、丝绸的流动感、珠宝的折射效果。"
            "整体气质：3A游戏大作水准、次世代角色设计、顶级CG品质。"
        ),
    }
    return suffixes.get(style_type, suffixes["真人电影风格"])


def _refine_character_prompt_with_llm(char: CharacterProfile, llm_service, style_type: str = None) -> str:
    """
    使用 LLM 精修角色图片提示词（强制使用 LLM，不回退）
    
    Args:
        char: 角色档案
        llm_service: LLM 服务实例
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
            f"LLM 服务不可用，无法生成角色 '{char.get('name', 'Unknown')}' 的图片提示词。"
            "请确保 ARK_API_KEY 已配置且 LLM 服务正常运行。"
        )
    
    system_prompt = _get_character_style_system_prompt(style_type)
    
    age_info = char.get('age', 'Unknown Age')
    ethnicity = char.get('ethnicity', '')
    user_prompt = f"角色: {char.get('name', 'Unknown')}. 种族: {ethnicity}. 年龄: {age_info}. 外貌: {char.get('appearance', '')}. 风格: {', '.join(char.get('style_tags', []))}."
    
    try:
        refined = llm_service.generate_text(system_prompt, user_prompt)
        if not refined:
            raise RuntimeError(f"LLM 返回空提示词，角色: {char.get('name', 'Unknown')}")
        return refined
    except Exception as e:
        raise RuntimeError(f"LLM 提示词精修失败，角色 '{char.get('name', 'Unknown')}': {e}")


def _build_character_image_prompt(char: CharacterProfile) -> str:
    """
    构建角色图片生成 Prompt（基础版本，作为 fallback）
    """
    name = char.get("name", "Unknown")
    appearance = char.get("appearance", "")
    age = char.get("age", "25 years old")
    ethnicity = char.get("ethnicity", "East Asian")
    style_tags = char.get("style_tags", [])
    visual_signature = char.get("visual_signature", "")
    
    # 构建种族标签
    ethnicity_tag = ""
    if "Chinese" in ethnicity or "East Asian" in ethnicity:
        ethnicity_tag = "Chinese face, East Asian features, black hair, dark eyes"
    
    # 构建年龄标签
    age_tag = age
    
    prompt = (
        f"{name}, {appearance}. "
        f"{visual_signature}. "
        f"{ethnicity_tag}, {age_tag}. "
        f"{', '.join(style_tags)}. "
        f"Official character reference sheet, white background, "
        f"bust shot showing full head, full body three-view (front, side, back). "
        f"Flat studio lighting, no shadows, 8k resolution."
    )
    
    return prompt


def format_character_sheet_for_prompt(sheet: CharacterSheet) -> str:
    """
    将角色档案格式化为可注入 Prompt 的文本段落。
    供分镜师 Agent 使用，确保 Image Prompt 保持角色一致性。
    """
    if not sheet or not sheet.get("main_characters"):
        return "（未提取到角色档案）"

    lines = []
    lines.append("## 🎨 世界观视觉信息")
    lines.append(f"- **整体风格**：{sheet.get('world_visual_style', '')}")
    lines.append(
        f"- **主色调（必须体现在每条 Prompt 中）**：`{sheet.get('color_palette', '')}`"
    )
    lines.append("")
    lines.append("## 👤 角色视觉档案（保持一致，不得偏离）")

    for char in sheet.get("main_characters", []):
        role_tag = {
            "protagonist": "主角",
            "antagonist": "反派",
            "supporting": "配角",
        }.get(char.get("role", ""), char.get("role", ""))
        lines.append(f"\n### {char.get('name', '')}（{role_tag}）")
        lines.append(f"- **外貌**：{char.get('appearance', '')}")
        lines.append(f"- **标志性视觉**：{char.get('visual_signature', '')}")
        lines.append(f"- **绘画关键词（必须使用）**：")
        lines.append(f"  ```")
        lines.append(f"  {char.get('image_keywords', '')}")
        lines.append(f"  ```")

    return "\n".join(lines)
