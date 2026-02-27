"""
agents/character_extractor.py
──────────────────────────────
角色提取 Agent：工作流的第一个节点，从原始网文中提取所有角色档案
和世界观视觉风格，供后续分镜师使用，保证全剧视觉一致性。

这是 v2 新增的节点，解决"每个场景角色外貌不统一"的核心问题。
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import SystemMessage, HumanMessage
from state import WorkflowState, CharacterSheet
from agents.llm_factory import get_llm
from agents.prompt_utils import render_prompt
from config import DEBUG


_PROMPT_PATH = (
    Path(__file__).parent.parent / "prompts" / "character_extractor_prompt.md"
)
_PROMPT_TEMPLATE = _PROMPT_PATH.read_text(encoding="utf-8")


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
    若提取失败，返回空档案（系统仍可继续运行，只是失去一致性保障）。
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
        print(
            f"✅ [角色提取 Agent] 完成！识别到 {len(chars)} 个角色：",
            "、".join(c.get("name", "?") for c in chars),
        )
        return {"character_sheet": sheet}
    except ValueError as e:
        print(f"⚠️  [角色提取 Agent] 解析失败（{e}），使用空档案继续")
        return {
            "character_sheet": {
                "main_characters": [],
                "world_visual_style": "未能自动提取，请参考原文",
                "color_palette": "",
            }
        }


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
