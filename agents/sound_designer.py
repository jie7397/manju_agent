"""
agents/sound_designer.py
─────────────────────────
音效师 Agent：为每个场景设计三层声音方案（环境音/动作音效/BGM）

工作守则摘要（详见 prompts/sound_designer_prompt.md）：
  1. 三层声音（Ambience / Foley / BGM Mood）缺一不可
  2. 同一时刻不超过3个声音层次
  3. 对白密集场景简化环境音
  4. BGM 需描述情绪弧线变化
"""

import json
import re
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import SystemMessage, HumanMessage
from state import WorkflowState, SoundScene
from agents.llm_factory import get_llm
from config import DEBUG
from agents.prompt_utils import render_prompt


_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "sound_designer_prompt.md"
_PROMPT_TEMPLATE = _PROMPT_PATH.read_text(encoding="utf-8")


def _format_director_feedback(feedbacks: list) -> str:
    if not feedbacks:
        return "无（首次创作）"
    relevant = [f for f in feedbacks if f.get("target_agent") == "sound_designer"]
    if not relevant:
        return "无针对音效师的修改意见"
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


def sound_designer_node(state: WorkflowState) -> dict:
    """
    LangGraph 节点函数：音效师 Agent

    读取 state 中的编剧剧本和分镜方案，
    输出三层声音设计到 state['sound_scenes']
    """
    print("\n🎵 [音效师 Agent] 开始工作...")

    director_feedback_text = _format_director_feedback(
        state.get("director_feedback", [])
    )

    screenplay_text = json.dumps(
        state.get("screenplay_scenes", []), ensure_ascii=False, indent=2
    )
    storyboard_text = json.dumps(
        state.get("storyboard_scenes", []), ensure_ascii=False, indent=2
    )

    prompt = render_prompt(
        _PROMPT_TEMPLATE,
        novel_type=state.get("novel_type", "仙侠/玄幻"),
        director_feedback=director_feedback_text,
        screenplay_scenes=screenplay_text,
        storyboard_scenes=storyboard_text,
    )

    if DEBUG:
        print(f"[DEBUG] 音效师 Prompt 长度: {len(prompt)} 字符")

    # 音效设计的创意度适中（temperature=0.5）
    llm = get_llm(temperature=0.5)
    messages = [
        SystemMessage(content=prompt),
        HumanMessage(
            content="请开始音效设计工作，严格按照要求输出 JSON 格式的音效方案列表。"
        ),
    ]

    response = llm.invoke(messages)
    raw_text = response.content

    if DEBUG:
        print(f"[DEBUG] 音效师原始输出:\n{raw_text[:500]}...")

    try:
        scenes: list[SoundScene] = _extract_json_from_response(raw_text)
        print(f"✅ [音效师 Agent] 完成！设计了 {len(scenes)} 个场景的音效方案")
    except ValueError as e:
        print(f"❌ [音效师 Agent] JSON 解析失败: {e}")
        scenes = [
            {
                "scene_number": 0,
                "ambience": "❌ 音效师输出解析失败",
                "foley": str(e),
                "bgm_mood": "请检查 LLM 的响应格式",
            }
        ]

    return {"sound_scenes": scenes}
