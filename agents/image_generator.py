"""
agents/image_generator.py
──────────────────────────────
图片生成 Agent：在导演审核通过后统一生成所有图片

v4 新增节点：
  - 从 character_sheet 和 locations 生成角色设定图和场景设定图
  - 节省成本：只有审核通过才生成图片

v5 更新：
  - 添加重试逻辑，失败自动重试
  - 敏感内容错误时跳过参考图重试
"""

import os
import re
import sys
import time
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from state import WorkflowState
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

# 重试配置
MAX_RETRIES = 3
RETRY_DELAY = 2  # 秒


def _generate_image_with_retry(service, prompt: str, output_path: str, reference_image_path: str = None, max_retries: int = MAX_RETRIES) -> tuple:
    """
    带重试的图片生成
    
    Returns:
        (success: bool, error_message: str or None)
    """
    last_error = None
    
    for attempt in range(max_retries):
        try:
            if reference_image_path:
                service.generate_image(prompt, output_path, reference_image_path=reference_image_path)
            else:
                service.generate_image(prompt, output_path)
            return True, None
        except Exception as e:
            last_error = str(e)
            error_lower = last_error.lower()
            
            # 敏感内容错误 - 尝试不带参考图重试
            if "sensitive" in error_lower or "敏感" in error_lower:
                if reference_image_path and attempt < max_retries - 1:
                    print(f"    ⚠️  检测到敏感内容，尝试不带参考图重试 ({attempt + 2}/{max_retries})...")
                    reference_image_path = None
                    time.sleep(RETRY_DELAY)
                    continue
            
            # 其他错误 - 正常重试
            if attempt < max_retries - 1:
                print(f"    ⚠️  生成失败，重试中 ({attempt + 2}/{max_retries})...")
                time.sleep(RETRY_DELAY)
            else:
                return False, last_error
    
    return False, last_error


def image_generator_node(state: WorkflowState) -> dict:
    """
    LangGraph 节点函数：图片生成 Agent
    
    在导演审核通过后，统一生成角色设定图和场景设定图。
    """
    print("\n🖼️  [图片生成 Agent] 开始生成图片...")

    character_sheet = state.get("character_sheet", {})
    locations_data = state.get("scene_images", {})  # production_designer 提取的场景信息
    
    character_images = {}
    scene_images = {}
    image_prompts = state.get("image_prompts", {})
    
    if not IMAGE_GEN_AVAILABLE or not os.environ.get("ARK_API_KEY"):
        print("  [Info] 图片生成未启用（缺少 ARK_API_KEY 或 SDK）")
        return {
            "character_images": character_images,
            "scene_images": scene_images,
            "image_prompts": image_prompts
        }
    
    service = SeeddreamService()
    llm_service = ArkLLMService() if LLM_SERVICE_AVAILABLE else None
    
    # 检查 LLM 服务是否可用
    if not llm_service or not llm_service.client:
        print("  ⚠️  LLM 服务不可用，无法生成图片提示词")
        return {
            "character_images": character_images,
            "scene_images": scene_images,
            "image_prompts": image_prompts
        }
    
    print(f"  [Info] 图片风格: {SUPPORTED_IMAGE_STYLES.get(IMAGE_STYLE_TYPE, {}).get('name', IMAGE_STYLE_TYPE)}")
    
    # ── 生成角色设定图 ──────────────────────────────────────────────────────
    chars = character_sheet.get("main_characters", [])
    if chars:
        base_output_dir = Path("output") / "character_images"
        base_output_dir.mkdir(parents=True, exist_ok=True)
        
        from agents.character_extractor import (
            _refine_character_prompt_with_llm, 
            _get_style_suffix
        )
        
        for char in chars:
            char_name = char.get("name", "unknown")
            cid = char_name.replace(" ", "_")
            
            # 每个角色一个独立文件夹
            char_dir = base_output_dir / cid
            char_dir.mkdir(parents=True, exist_ok=True)
            
            try:
                refined = _refine_character_prompt_with_llm(char, llm_service, IMAGE_STYLE_TYPE)
                print(f"  [LLM] 精修提示词: {char_name} -> {refined[:50]}...")
            except RuntimeError as e:
                print(f"  ⚠️  LLM 提示词精修失败: {e}")
                continue
            
            # 追加年龄标签（中文）
            age_info = char.get('age', '')
            age_suffix = ""
            if age_info:
                match = re.search(r"(\d+)", age_info)
                if match:
                    age_suffix = f"，{match.group(1)}岁"
                elif "中年" in age_info or "middle" in age_info.lower():
                    age_suffix = "，中年人"
                elif "老" in age_info or "old" in age_info.lower() or "elder" in age_info.lower():
                    age_suffix = "，老年人"
                elif "少" in age_info or "young" in age_info.lower():
                    age_suffix = "，年轻人"
            
            # 追加种族标签（中文）
            ethnicity_tag = ""
            ethnicity = char.get('ethnicity', '')
            if "Chinese" in ethnicity or "East Asian" in ethnicity:
                ethnicity_tag = "，中国面孔，东方面孔特征，黑发，深色眼睛"
            elif not ethnicity:
                if any(ord(c) > 127 for c in char.get('name', '')):
                    ethnicity_tag = "，中国面孔，东方面孔特征，黑发，深色眼睛"
            
            style_suffix = _get_style_suffix(IMAGE_STYLE_TYPE)
            base_prompt = refined + ethnicity_tag + age_suffix + style_suffix
            
            # 方案：分开生成大头图和全身三视图，避免全身图面部变形
            # 第一步：生成高质量大头图（保证面部清晰）
            headshot_prompt = (
                f"{base_prompt}的标准胸像特写。"
                f"构图：标准胸像，从胸部以上到头顶完整展示。"
                f"面部要求：正脸平视，五官清晰精致，眼睛有神，皮肤纹理真实。"
                f"头部上方必须留有空白，严禁切顶。"
                f"背景：纯白背景，无干扰。"
                f"光影：平光演播室照明，柔和均匀，无阴影。"
                f"画质：8k分辨率，超高细节，专业人像摄影。"
                f"负面提示：裁切头部、切顶、出画、面部变形、五官扭曲、模糊面部、不对称、畸变、扭曲的脸、丑陋的面部、动漫、插画、CG"
            )
            headshot_path = char_dir / "headshot.png"
            headshot_generated = False
            
            # 使用重试函数生成大头图
            success, error = _generate_image_with_retry(service, headshot_prompt, str(headshot_path))
            if success:
                character_images[cid] = {
                    "headshot": str(headshot_path),
                    "headshot_prompt": headshot_prompt,
                    "folder": str(char_dir),
                }
                print(f"  🖼️  生成大头图: {char_name}")
                headshot_generated = True
            else:
                print(f"  ⚠️  大头图生成失败 ({char_name}): {error}")
            
            # 第二步：生成全身三视图（使用大头图作为参考，保持面部一致性）
            body_prompt = (
                f"{base_prompt}的全身三视图设定图。"
                f"构图：并排展示正视图、侧视图、背视图三个视角，必须拉远镜头确保全身完整入画。"
                f"**关键要求**：每个视角必须从头到脚完整展示，头部到脚底全部在画面内，严禁裁剪任何身体部位。"
                f"**必须包含**：完整的双腿、双脚、脚尖必须可见。镜头必须足够远，确保角色周围有充足留白。"
                f"**面部要求**：头部必须清晰，面部五官与参考图完全一致，严禁变形模糊。"
                f"服装：三个视角服装颜色、款式必须完全一致。"
                f"站姿：标准直立站姿，双脚并拢或微张，双手自然下垂。"
                f"背景：纯白背景，无干扰，角色周围留有充足空白。"
                f"光影：平光演播室照明，柔和均匀。"
                f"画质：8k分辨率，专业角色设计图，广角全身镜头。"
                f"负面提示：裁切、切顶、切底、出画、缺失手臂、缺失腿部、缺失脚部、没有脚、截断腿部、半身、面部变形、五官扭曲、模糊面部、不对称、畸变"
            )
            
            body_path = char_dir / "body.png"
            ref_path = str(headshot_path) if headshot_generated else None
            
            # 使用重试函数生成全身三视图
            success, error = _generate_image_with_retry(service, body_prompt, str(body_path), reference_image_path=ref_path)
            if success:
                if headshot_generated:
                    print(f"  🖼️  生成全身三视图: {char_name}（使用大头图参考）")
                else:
                    print(f"  🖼️  生成全身三视图: {char_name}")
                
                if cid not in character_images:
                    character_images[cid] = {"folder": str(char_dir)}
                character_images[cid]["body_sheet"] = str(body_path)
                character_images[cid]["body_prompt"] = body_prompt
                character_images[cid]["base_prompt"] = refined
            else:
                print(f"  ⚠️  全身三视图生成失败 ({char_name}): {error}")
            
            image_prompts[f"char_{cid}_headshot"] = headshot_prompt
            image_prompts[f"char_{cid}_body"] = body_prompt
    
    # ── 生成场景设定图 ──────────────────────────────────────────────────────
    # 从 production_designer_node 的输出获取场景信息
    # 注意：production_designer 现在只提取场景信息，不生成图片
    # 我们需要从 screenplay_scenes 中提取场景
    
    screenplay_scenes = state.get("screenplay_scenes", [])
    if screenplay_scenes:
        output_dir = Path("output") / "scene_images"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        from agents.production_designer import (
            _refine_scene_prompt_with_llm,
            _get_scene_style_suffix
        )
        
        # 提取场景信息（简化版，从 screenplay_scenes 中提取 setting）
        seen_settings = set()
        locations = []
        for scene in screenplay_scenes:
            setting = scene.get("setting", "")
            if setting and setting not in seen_settings:
                seen_settings.add(setting)
                locations.append({
                    "location_id": f"loc_{len(locations)+1:03d}",
                    "name": setting,
                    "description": scene.get("visual_hint", setting)
                })
        
        style_tags = ["电影质感", "概念设计"]
        
        for loc in locations:
            lid = loc.get("location_id", "unknown")
            
            try:
                refined = _refine_scene_prompt_with_llm(loc, llm_service, style_tags, IMAGE_STYLE_TYPE)
                style_suffix = _get_scene_style_suffix(IMAGE_STYLE_TYPE)
                base_prompt = refined + style_suffix
                print(f"  [LLM] 精修场景提示词: {loc.get('name')} -> {refined[:50]}...")
            except RuntimeError as e:
                print(f"  ⚠️  LLM 场景提示词精修失败: {e}")
                continue
            
            final_prompt = (
                f"{base_prompt}。"
                f"大师级环境概念设计，8k分辨率，超高细节。"
                f"广角镜头，史诗感，电影级布光。"
                f"无人空镜。"
            )
            image_prompts[f"scene_{lid}"] = final_prompt
            
            image_path = output_dir / f"{lid}_anchor.png"
            try:
                service.generate_image(final_prompt, str(image_path))
                scene_images[lid] = {
                    "scene_anchor": str(image_path),
                    "prompt": final_prompt,
                    "base_prompt": base_prompt
                }
                print(f"  🖼️  生成场景设定图: {loc.get('name')}")
            except Exception as e:
                print(f"  ⚠️  场景图片生成失败 ({loc.get('name')}): {e}")
    
    print(f"✅ [图片生成 Agent] 完成！生成 {len(character_images)} 个角色图，{len(scene_images)} 个场景图")
    
    # ── 保存所有提示词到JSON文件，方便用户自己生成 ───────────────────────────
    _save_prompts_to_file(character_images, scene_images, image_prompts)
    
    return {
        "character_images": character_images,
        "scene_images": scene_images,
        "image_prompts": image_prompts
    }


def _save_prompts_to_file(character_images: dict, scene_images: dict, image_prompts: dict):
    """
    保存所有图片提示词到JSON文件，方便用户自己用其他工具生成
    """
    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prompts_file = output_dir / f"image_prompts_{timestamp}.json"
    
    # 构建完整的提示词数据
    prompts_data = {
        "generated_at": datetime.now().isoformat(),
        "style": IMAGE_STYLE_TYPE,
        "characters": {},
        "scenes": {},
        "all_prompts": image_prompts
    }
    
    # 角色提示词详情
    for cid, data in character_images.items():
        char_dir = Path(data.get("folder", ""))
        prompts_data["characters"][cid] = {
            "folder": str(char_dir),
            "images": {}
        }
        
        # 大头图
        if "headshot" in data:
            prompts_data["characters"][cid]["images"]["headshot"] = {
                "file": data["headshot"],
                "prompt": data.get("headshot_prompt", ""),
                "description": "标准胸像特写，用于面部参考"
            }
        
        # 全身三视图
        if "body_sheet" in data:
            prompts_data["characters"][cid]["images"]["body"] = {
                "file": data["body_sheet"],
                "prompt": data.get("body_prompt", ""),
                "base_prompt": data.get("base_prompt", ""),
                "description": "全身三视图设定图"
            }
    
    # 场景提示词详情
    for lid, data in scene_images.items():
        prompts_data["scenes"][lid] = {
            "file": data.get("scene_anchor", ""),
            "prompt": data.get("prompt", ""),
            "base_prompt": data.get("base_prompt", "")
        }
    
    # 保存JSON文件
    with open(prompts_file, "w", encoding="utf-8") as f:
        json.dump(prompts_data, f, ensure_ascii=False, indent=2)
    
    print(f"  📝 提示词已保存到: {prompts_file}")
    
    # 同时保存一份纯文本版本，方便直接复制使用
    txt_file = output_dir / f"image_prompts_{timestamp}.txt"
    with open(txt_file, "w", encoding="utf-8") as f:
        f.write("=" * 60 + "\n")
        f.write(f"图片生成提示词 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"风格: {IMAGE_STYLE_TYPE}\n")
        f.write("=" * 60 + "\n\n")
        
        # 角色提示词
        f.write("【角色提示词】\n\n")
        for cid, data in character_images.items():
            f.write(f"── {cid} ──\n")
            if "headshot_prompt" in data:
                f.write("[大头图]\n")
                f.write(f"{data['headshot_prompt']}\n\n")
            if "body_prompt" in data:
                f.write("[全身三视图]\n")
                f.write(f"{data['body_prompt']}\n\n")
            f.write("\n")
        
        # 场景提示词
        f.write("\n【场景提示词】\n\n")
        for lid, data in scene_images.items():
            f.write(f"── {lid} ──\n")
            f.write(f"{data.get('prompt', '')}\n\n")
        
        # 所有提示词列表
        f.write("\n【所有提示词索引】\n\n")
        for key, prompt in image_prompts.items():
            f.write(f"[{key}]\n")
            f.write(f"{prompt}\n\n")
    
    print(f"  ?? 文本版本: {txt_file}")