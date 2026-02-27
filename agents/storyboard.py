"""
agents/storyboard.py
─────────────────────
分镜师 Agent：将编剧的场景剧本转化为可供 AI 绘画的视觉指令

工作守则摘要（详见 prompts/storyboard_prompt.md）：
  1. 每个 Prompt 必须覆盖主体/环境/光影/镜头四个维度
  2. 严格使用标准景别和角度词汇
  3. 末尾附加对应小说类型的风格标签和画幅比例
  4. 旁白场景参考 visual_hint 描绘空镜
"""

import json
import re
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import SystemMessage, HumanMessage
from state import WorkflowState, StoryboardScene
from agents.llm_factory import get_llm
from config import DEBUG
from agents.prompt_utils import render_prompt
from agents.character_extractor import format_character_sheet_for_prompt


_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "storyboard_prompt.md"
_PROMPT_TEMPLATE = _PROMPT_PATH.read_text(encoding="utf-8")


def _format_director_feedback(feedbacks: list) -> str:
    if not feedbacks:
        return "无（首次创作）"
    relevant = [f for f in feedbacks if f.get("target_agent") == "storyboard"]
    if not relevant:
        return "无针对分镜师的修改意见"
    lines = []
    for fb in relevant:
        scene = f"场景{fb['scene_number']}" if fb["scene_number"] != -1 else "全局"
        lines.append(f"【{scene}】{fb['issue']}\n→ 修改指令：{fb['instruction']}")
    return "\n\n".join(lines)


def _extract_json_from_response(text: str) -> list:
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    pattern = r"```(?:json)?\s*([\s\S]+?)\s*```"
    match = re.search(pattern, text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"无法从 LLM 响应中解析 JSON，原始响应前200字符：\n{text[:200]}")


def storyboard_node(state: WorkflowState) -> dict:
    """
    LangGraph 节点函数：分镜师 Agent

    读取 state 中的编剧场景列表，
    输出每个场景的绘画 Prompt 和运镜说明到 state['storyboard_scenes']
    """
    print("\n🖼️  [分镜师 Agent] 开始工作...")

    director_feedback_text = _format_director_feedback(
        state.get("director_feedback", [])
    )

    # 将编剧场景序列化为文本供 LLM 读取
    screenplay_text = json.dumps(
        state.get("screenplay_scenes", []), ensure_ascii=False, indent=2
    )

    # 注入角色档案（v2 新增：保证角色视觉一致性）
    character_sheet = state.get("character_sheet")
    character_sheet_text = (
        format_character_sheet_for_prompt(character_sheet)
        if character_sheet
        else "（未提取到角色档案）"
    )

    prompt = render_prompt(
        _PROMPT_TEMPLATE,
        novel_type=state.get("novel_type", "仙侠/玄幻"),
        director_feedback=director_feedback_text,
        screenplay_scenes=screenplay_text,
        character_sheet=character_sheet_text,
    )

    if DEBUG:
        print(f"[DEBUG] 分镜师 Prompt 长度: {len(prompt)} 字符")

    # 分镜师也需要一定创意（temperature=0.6，略低于编剧）
    llm = get_llm(temperature=0.6)
    messages = [
        SystemMessage(content=prompt),
        HumanMessage(
            content="请开始分镜设计工作，严格按照要求输出 JSON 格式的分镜列表。"
        ),
    ]

    response = llm.invoke(messages)
    raw_text = response.content

    if DEBUG:
        print(f"[DEBUG] 分镜师原始输出:\n{raw_text[:500]}...")

    try:
        scenes: list[StoryboardScene] = _extract_json_from_response(raw_text)
        print(f"✅ [分镜师 Agent] 完成！生成了 {len(scenes)} 个分镜方案")
    except ValueError as e:
        print(f"❌ [分镜师 Agent] JSON 解析失败: {e}")
        scenes = [
            {
                "scene_number": 0,
                "shot_type": "❌ 分镜师输出解析失败",
                "image_prompt": str(e),
                "camera_movement": "",
                "visual_notes": "请检查 LLM 的响应格式",
            }
        ]

    return {"storyboard_scenes": scenes}
