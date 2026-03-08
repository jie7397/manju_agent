#!/usr/bin/env python3
"""
regenerate_image.py
────────────────────────
重新生成单张角色图片的工具脚本

用法：
    # 重新生成某个角色的大头图
    python regenerate_image.py --character 萧仁 --type headshot
    
    # 重新生成某个角色的全身三视图
    python regenerate_image.py --character 萧仁 --type body
    
    # 重新生成某个角色的所有图片
    python regenerate_image.py --character 萧仁 --type all
    
    # 列出所有可用的角色
    python regenerate_image.py --list
    
    # 指定画风
    python regenerate_image.py --character 萧仁 --type headshot --style 动漫风格
"""

import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))

from config import IMAGE_STYLE_TYPE, SUPPORTED_IMAGE_STYLES
from services.image_gen import SeeddreamService
from services.llm import ArkLLMService


def list_available_characters():
    """列出所有可用的角色"""
    output_dir = Path("output") / "character_images"
    if not output_dir.exists():
        print("❌ 还没有生成任何角色图片")
        return
    
    characters = [d for d in output_dir.iterdir() if d.is_dir()]
    if not characters:
        print("❌ 还没有生成任何角色图片")
        return
    
    print("\n📋 已生成的角色：")
    print("-" * 40)
    for char_dir in sorted(characters):
        headshot = char_dir / "headshot.png"
        body = char_dir / "body.png"
        status = []
        if headshot.exists():
            status.append("大头图✅")
        else:
            status.append("大头图❌")
        if body.exists():
            status.append("全身图✅")
        else:
            status.append("全身图❌")
        print(f"  • {char_dir.name}: {', '.join(status)}")
    print("-" * 40)


def load_character_info(char_name: str) -> dict:
    """从最新的 raw_data 文件加载角色信息"""
    output_dir = Path("output")
    if not output_dir.exists():
        return None
    
    # 查找最新的 raw_data 文件
    raw_data_files = sorted(output_dir.glob("raw_data_*.json"), reverse=True)
    if not raw_data_files:
        return None
    
    for raw_file in raw_data_files:
        try:
            with open(raw_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            char_sheet = data.get("character_sheet", {})
            for char in char_sheet.get("main_characters", []):
                if char.get("name") == char_name:
                    return char
        except:
            continue
    
    return None


def regenerate_headshot(char_name: str, char_info: dict, style_type: str, service: SeeddreamService, llm_service: ArkLLMService):
    """重新生成大头图
    
    Returns:
        dict with 'success', 'prompt', 'base_prompt', 'path' or None on failure
    """
    from agents.character_extractor import (
        _refine_character_prompt_with_llm,
        _get_style_suffix
    )
    import re
    
    print(f"\n🔄 重新生成 {char_name} 的大头图...")
    
    # 精修提示词
    try:
        refined = _refine_character_prompt_with_llm(char_info, llm_service, style_type)
        print(f"  [LLM] 精修提示词: {refined[:50]}...")
    except Exception as e:
        print(f"  ❌ LLM 提示词精修失败: {e}")
        return None
    
    # 追加标签
    age_info = char_info.get('age', '')
    age_suffix = ""
    if age_info:
        match = re.search(r"(\d+)", age_info)
        if match:
            age_suffix = f"，{match.group(1)}岁"
    
    ethnicity_tag = ""
    ethnicity = char_info.get('ethnicity', '')
    if "Chinese" in ethnicity or "East Asian" in ethnicity:
        ethnicity_tag = "，中国面孔，东方面孔特征，黑发，深色眼睛"
    
    style_suffix = _get_style_suffix(style_type)
    base_prompt = refined + ethnicity_tag + age_suffix + style_suffix
    
    # 构建 prompt
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
    
    # 输出路径
    char_dir = Path("output") / "character_images" / char_name.replace(" ", "_")
    char_dir.mkdir(parents=True, exist_ok=True)
    headshot_path = char_dir / "headshot.png"
    
    # 生成图片
    try:
        service.generate_image(headshot_prompt, str(headshot_path))
        print(f"  ✅ 大头图生成成功: {headshot_path}")
        return {
            "success": True,
            "prompt": headshot_prompt,
            "base_prompt": base_prompt,
            "path": str(headshot_path)
        }
    except Exception as e:
        print(f"  ❌ 大头图生成失败: {e}")
        return {
            "success": False,
            "prompt": headshot_prompt,
            "base_prompt": base_prompt,
            "error": str(e)
        }


def regenerate_body(char_name: str, char_info: dict, style_type: str, service: SeeddreamService, llm_service: ArkLLMService, use_reference: bool = True):
    """重新生成全身三视图
    
    Returns:
        dict with 'success', 'prompt', 'base_prompt', 'path', 'used_reference' or None on failure
    """
    from agents.character_extractor import (
        _refine_character_prompt_with_llm,
        _get_style_suffix
    )
    import re
    
    print(f"\n🔄 重新生成 {char_name} 的全身三视图...")
    
    # 精修提示词
    try:
        refined = _refine_character_prompt_with_llm(char_info, llm_service, style_type)
        print(f"  [LLM] 精修提示词: {refined[:50]}...")
    except Exception as e:
        print(f"  ❌ LLM 提示词精修失败: {e}")
        return None
    
    # 追加标签
    age_info = char_info.get('age', '')
    age_suffix = ""
    if age_info:
        match = re.search(r"(\d+)", age_info)
        if match:
            age_suffix = f"，{match.group(1)}岁"
    
    ethnicity_tag = ""
    ethnicity = char_info.get('ethnicity', '')
    if "Chinese" in ethnicity or "East Asian" in ethnicity:
        ethnicity_tag = "，中国面孔，东方面孔特征，黑发，深色眼睛"
    
    style_suffix = _get_style_suffix(style_type)
    base_prompt = refined + ethnicity_tag + age_suffix + style_suffix
    
    # 构建 prompt
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
    
    # 输出路径
    char_dir = Path("output") / "character_images" / char_name.replace(" ", "_")
    char_dir.mkdir(parents=True, exist_ok=True)
    body_path = char_dir / "body.png"
    
    # 参考图
    ref_path = None
    if use_reference:
        headshot_path = char_dir / "headshot.png"
        if headshot_path.exists():
            ref_path = str(headshot_path)
            print(f"  [Info] 使用大头图作为参考")
    
    # 生成图片
    try:
        if ref_path:
            service.generate_image(body_prompt, str(body_path), reference_image_path=ref_path)
        else:
            service.generate_image(body_prompt, str(body_path))
        print(f"  ✅ 全身三视图生成成功: {body_path}")
        return {
            "success": True,
            "prompt": body_prompt,
            "base_prompt": base_prompt,
            "path": str(body_path),
            "used_reference": ref_path is not None
        }
    except Exception as e:
        print(f"  ❌ 全身三视图生成失败: {e}")
        return {
            "success": False,
            "prompt": body_prompt,
            "base_prompt": base_prompt,
            "error": str(e)
        }


def _save_regenerate_prompts(char_name: str, style_type: str, headshot_result: dict, body_result: dict):
    """保存重新生成的提示词到文件"""
    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prompts_file = output_dir / f"regenerate_prompts_{char_name}_{timestamp}.json"
    
    prompts_data = {
        "generated_at": datetime.now().isoformat(),
        "character": char_name,
        "style": style_type,
        "headshot": headshot_result,
        "body": body_result
    }
    
    with open(prompts_file, "w", encoding="utf-8") as f:
        json.dump(prompts_data, f, ensure_ascii=False, indent=2)
    
    print(f"  📝 提示词已保存到: {prompts_file}")
    
    # 保存纯文本版本
    txt_file = output_dir / f"regenerate_prompts_{char_name}_{timestamp}.txt"
    with open(txt_file, "w", encoding="utf-8") as f:
        f.write("=" * 60 + "\n")
        f.write(f"重新生成提示词 - {char_name}\n")
        f.write(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"风格: {style_type}\n")
        f.write("=" * 60 + "\n\n")
        
        if headshot_result:
            f.write("【大头图】\n")
            f.write(f"状态: {'成功' if headshot_result.get('success') else '失败'}\n")
            f.write(f"路径: {headshot_result.get('path', 'N/A')}\n\n")
            f.write("提示词:\n")
            f.write(f"{headshot_result.get('prompt', 'N/A')}\n\n")
            f.write("基础提示词:\n")
            f.write(f"{headshot_result.get('base_prompt', 'N/A')}\n\n")
            f.write("-" * 60 + "\n\n")
        
        if body_result:
            f.write("【全身三视图】\n")
            f.write(f"状态: {'成功' if body_result.get('success') else '失败'}\n")
            f.write(f"路径: {body_result.get('path', 'N/A')}\n")
            f.write(f"使用参考图: {'是' if body_result.get('used_reference') else '否'}\n\n")
            f.write("提示词:\n")
            f.write(f"{body_result.get('prompt', 'N/A')}\n\n")
            f.write("基础提示词:\n")
            f.write(f"{body_result.get('base_prompt', 'N/A')}\n\n")
    
    print(f"  📄 文本版本: {txt_file}")


def main():
    parser = argparse.ArgumentParser(
        description="重新生成单张角色图片",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--character", "-c", help="角色名称")
    parser.add_argument("--type", "-t", choices=["headshot", "body", "all"], default="all", help="图片类型")
    parser.add_argument("--style", "-s", choices=list(SUPPORTED_IMAGE_STYLES.keys()), help="画风")
    parser.add_argument("--list", "-l", action="store_true", help="列出所有可用角色")
    parser.add_argument("--no-reference", action="store_true", help="生成全身图时不使用参考图")
    
    args = parser.parse_args()
    
    # 列出角色
    if args.list:
        list_available_characters()
        return
    
    # 检查角色名称
    if not args.character:
        print("❌ 请指定角色名称，使用 --character 或 -c 参数")
        print("   示例: python regenerate_image.py -c 萧仁 -t headshot")
        return
    
    # 设置画风
    style_type = args.style or IMAGE_STYLE_TYPE
    print(f"🎨 当前画风: {style_type}")
    
    # 初始化服务
    service = SeeddreamService()
    llm_service = ArkLLMService()
    
    if not service.client:
        print("❌ 图片生成服务不可用，请检查 ARK_API_KEY")
        return
    
    if not llm_service.client:
        print("❌ LLM 服务不可用，请检查 ARK_API_KEY")
        return
    
    # 加载角色信息
    char_info = load_character_info(args.character)
    if not char_info:
        print(f"❌ 找不到角色 '{args.character}' 的信息")
        print("   请先运行主程序生成角色数据")
        return
    
    print(f"📝 角色信息: {char_info.get('name')}, 年龄: {char_info.get('age', '未知')}")
    
    # 生成图片
    use_reference = not args.no_reference
    headshot_result = None
    body_result = None
    
    if args.type in ["headshot", "all"]:
        headshot_result = regenerate_headshot(args.character, char_info, style_type, service, llm_service)
    
    if args.type in ["body", "all"]:
        body_result = regenerate_body(args.character, char_info, style_type, service, llm_service, use_reference)
    
    # 保存提示词
    if headshot_result or body_result:
        _save_regenerate_prompts(args.character, style_type, headshot_result, body_result)
    
    print("\n✅ 完成！")


if __name__ == "__main__":
    main()