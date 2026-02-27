"""
agents/screenwriter.py
──────────────────────
编剧 Agent：将网文原文改编为结构化的漫剧场景剧本（JSON 格式）

工作守则摘要（详见 prompts/screenwriter_prompt.md）：
  1. 根据小说类型动态调整台词风格
  2. 心理描写必须转化为 VO/OS，不得删除
  3. 纯设定段落提炼为旁白 + visual_hint
  4. 输出严格的 JSON 数组格式
"""

import json
import re
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import SystemMessage, HumanMessage
from state import WorkflowState, ScreenplayScene
from agents.llm_factory import get_llm
from config import DEBUG
from agents.prompt_utils import render_prompt


# 加载 Prompt 模板
_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "screenwriter_prompt.md"
_PROMPT_TEMPLATE = _PROMPT_PATH.read_text(encoding="utf-8")


def _format_director_feedback(feedbacks: list) -> str:
    """将导演反馈格式化为可读文本，过滤出仅针对编剧的部分"""
    if not feedbacks:
        return "无（首次创作）"

    relevant = [f for f in feedbacks if f.get("target_agent") == "screenwriter"]
    if not relevant:
        return "无针对编剧的修改意见"

    lines = []
    for fb in relevant:
        scene = f"场景{fb['scene_number']}" if fb["scene_number"] != -1 else "全局"
        lines.append(f"【{scene}】{fb['issue']}\n→ 修改指令：{fb['instruction']}")
    return "\n\n".join(lines)


def _extract_json_from_response(text: str) -> list:
    """
    从 LLM 的响应中提取 JSON 数组。
    LLM 有时会在 JSON 前后加上 ```json ``` 的 Markdown 包装，需要剥离。
    """
    # 尝试直接解析
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # 尝试提取 ```json ... ``` 代码块
    pattern = r"```(?:json)?\s*([\s\S]+?)\s*```"
    match = re.search(pattern, text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 尝试找到第一个 [ 到最后一个 ] 之间的内容
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"无法从 LLM 响应中解析 JSON，原始响应前200字符：\n{text[:200]}")


def screenwriter_node(state: WorkflowState) -> dict:
    """
    LangGraph 节点函数：编剧 Agent

    读取 state 中的原始网文和导演反馈，
    输出结构化的场景列表到 state['screenplay_scenes']
    """
    print("\n🎬 [编剧 Agent] 开始工作...")

    # 构建 Prompt
    director_feedback_text = _format_director_feedback(
        state.get("director_feedback", [])
    )

    prompt = render_prompt(
        _PROMPT_TEMPLATE,
        novel_type=state.get("novel_type", "仙侠/玄幻"),
        director_feedback=director_feedback_text,
        novel_text=state["novel_text"],
    )

    if DEBUG:
        print(f"[DEBUG] 编剧 Prompt 长度: {len(prompt)} 字符")

    # 调用 LLM（编剧需要一些创意，temperature=0.7）
    llm = get_llm(temperature=0.7)
    messages = [
        SystemMessage(content=prompt),
        HumanMessage(content="请开始改编工作，严格按照要求输出 JSON 格式的场景列表。"),
    ]

    response = llm.invoke(messages)
    raw_text = response.content

    if DEBUG:
        print(f"[DEBUG] 编剧原始输出:\n{raw_text[:500]}...")

    # 解析 JSON
    try:
        scenes: list[ScreenplayScene] = _extract_json_from_response(raw_text)
        print(f"✅ [编剧 Agent] 完成！生成了 {len(scenes)} 个场景")
    except ValueError as e:
        print(f"❌ [编剧 Agent] JSON 解析失败: {e}")
        # 降级处理：返回一个错误占位场景
        scenes = [
            {
                "scene_number": 0,
                "setting": "❌ 编剧输出解析失败",
                "action": str(e),
                "dialogue": [],
                "visual_hint": "请检查 LLM 的响应格式",
            }
        ]

    return {"screenplay_scenes": scenes}
