"""
agents/director.py
───────────────────
导演 Agent：审核三个创作 Agent 的输出，决定通过或打回修改

导演实现了"带审核的循环"工作流的核心逻辑：
  - 输出 decision: "APPROVE" → 工作流结束，进入最终输出
  - 输出 decision: "REVISE" → 指定目标 Agent 打回重做

四大审核维度：
  1. 忠实度（编剧）：剧情不得偏离原文
  2. 情绪张力（编剧+音效）：情绪起伏要大
  3. 视觉丰满度（分镜师）：画面要丰富饱满
  4. 声音清晰度（音效师）：声音不能太杂乱
"""

import json
import re
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import SystemMessage, HumanMessage
from state import WorkflowState, DirectorFeedback
from agents.llm_factory import get_llm
from config import DEBUG, MAX_REVISIONS
from agents.prompt_utils import render_prompt


_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "director_prompt.md"
_PROMPT_TEMPLATE = _PROMPT_PATH.read_text(encoding="utf-8")


def _extract_json_from_response(text: str) -> dict:
    """从 LLM 响应中提取 JSON 对象（注意：导演输出的是 dict 不是 list）"""
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
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"无法从导演响应中解析 JSON，原始响应前200字符：\n{text[:200]}")


def _determine_primary_revision_target(feedbacks: list[DirectorFeedback]) -> str:
    """
    当有多个 Agent 需要修改时，决定主要退回目标。
    优先级：character_extractor > production_designer > screenwriter > storyboard > sound_designer
    （因为角色是基础，改了角色之后，其他往往需要跟着更新）
    """
    targets = {fb["target_agent"] for fb in feedbacks}
    if "character_extractor" in targets:
        return "character_extractor"
    elif "production_designer" in targets:
        return "production_designer"
    elif "screenwriter" in targets:
        return "screenwriter"
    elif "storyboard" in targets:
        return "storyboard"
    elif "sound_designer" in targets:
        return "sound_designer"
    return "approved"


def director_node(state: WorkflowState) -> dict:
    """
    LangGraph 节点函数：导演 Agent

    审核三个创作 Agent 的成果，更新 state 中的：
      - director_feedback: 具体的退回意见
      - revision_target: 需要修改的主要 Agent（或 "approved"）
      - revision_count: 递增的轮次计数
      - is_approved: 是否最终批准
      - final_script: 若批准，生成最终格式化的完整剧本文本
    """
    print("\n🎬 [导演 Agent] 开始审核...")

    revision_count = state.get("revision_count", 0) + 1

    # ── 超出最大迭代次数时强制通过（防止死循环）──────────────────────────────────
    if revision_count > MAX_REVISIONS:
        print(f"⚠️  [导演 Agent] 已达到最大审核轮数 ({MAX_REVISIONS})，强制通过。")
        return {
            "revision_target": "approved",
            "is_approved": True,
            "revision_count": revision_count,
            "director_feedback": [],
            "final_script": _format_final_script(state),
        }

    # ── 构建分析 Prompt ──────────────────────────────────────────────────────────
    # v3: 增加图片 Prompt 审核
    image_prompts = state.get("image_prompts", {})
    character_prompts = {k: v for k, v in image_prompts.items() if k.startswith("char_") or not k.startswith("scene_")}
    scene_prompts = {k: v for k, v in image_prompts.items() if k.startswith("scene_")}
    
    prompt = render_prompt(
        _PROMPT_TEMPLATE,
        novel_text=state.get("novel_text", ""),
        screenplay_scenes=json.dumps(
            state.get("screenplay_scenes", []), ensure_ascii=False, indent=2
        ),
        storyboard_scenes=json.dumps(
            state.get("storyboard_scenes", []), ensure_ascii=False, indent=2
        ),
        sound_scenes=json.dumps(
            state.get("sound_scenes", []), ensure_ascii=False, indent=2
        ),
        character_prompts=json.dumps(character_prompts, ensure_ascii=False, indent=2),
        scene_prompts=json.dumps(scene_prompts, ensure_ascii=False, indent=2),
        revision_count=revision_count,
    )

    if DEBUG:
        print(f"[DEBUG] 导演 Prompt 长度: {len(prompt)} 字符")

    # 导演审核需要严格、准确（temperature=0.2）
    llm = get_llm(temperature=0.2)
    messages = [
        SystemMessage(content=prompt),
        HumanMessage(content="请开始审核，输出你的决策 JSON。"),
    ]

    response = llm.invoke(messages)
    raw_text = response.content

    if DEBUG:
        print(f"[DEBUG] 导演原始输出:\n{raw_text}")

    # ── 解析导演决策 ──────────────────────────────────────────────────────────────
    try:
        decision_data = _extract_json_from_response(raw_text)
    except ValueError as e:
        print(f"❌ [导演 Agent] 决策解析失败: {e}，默认通过")
        return {
            "revision_target": "approved",
            "is_approved": True,
            "revision_count": revision_count,
            "director_feedback": [],
            "final_script": _format_final_script(state),
        }

    decision = decision_data.get("decision", "APPROVE")
    feedbacks: list[DirectorFeedback] = decision_data.get("feedbacks", [])

    if decision == "APPROVE":
        print(f"✅ [导演 Agent] 审核通过！（第 {revision_count} 轮）")
        print(f"   评语：{decision_data.get('summary', '')}")
        return {
            "revision_target": "approved",
            "is_approved": True,
            "revision_count": revision_count,
            "director_feedback": [],
            "final_script": _format_final_script(state),
        }
    else:
        primary_target = _determine_primary_revision_target(feedbacks)
        print(
            f"🔄 [导演 Agent] 审核不通过（第 {revision_count} 轮），退回给：{primary_target}"
        )
        for fb in feedbacks:
            scene = f"场景{fb['scene_number']}" if fb["scene_number"] != -1 else "全局"
            print(f"   [{fb['target_agent']}·{scene}] {fb['issue']}")
        return {
            "revision_target": primary_target,
            "is_approved": False,
            "revision_count": revision_count,
            "director_feedback": feedbacks,
        }


def _format_final_script(state: WorkflowState) -> str:
    """
    将三个 Agent 的输出合并为人类可读的最终漫剧剧本文本。
    这份文本是面向制作团队的完整工作文档。
    """
    lines = []
    lines.append("=" * 60)
    lines.append("漫剧剧本 · 最终版")
    lines.append(f"类型：{state.get('novel_type', '未知')}")
    lines.append("=" * 60)

    screenplay_scenes = state.get("screenplay_scenes", [])
    storyboard_scenes = state.get("storyboard_scenes", [])
    sound_scenes = state.get("sound_scenes", [])

    # 建立场景号索引便于快速查找
    storyboard_idx = {s["scene_number"]: s for s in storyboard_scenes}
    sound_idx = {s["scene_number"]: s for s in sound_scenes}

    for scene in screenplay_scenes:
        num = scene["scene_number"]
        lines.append(f"\n{'─' * 40}")
        lines.append(f"【第 {num} 场】  {scene['setting']}")
        lines.append(f"{'─' * 40}")

        # 动作描写
        if scene.get("action"):
            lines.append(f"\n📌 动作：{scene['action']}")

        # 台词
        if scene.get("dialogue"):
            lines.append("\n📝 台词：")
            for dlg in scene["dialogue"]:
                type_tag = {"VO": "【旁白】", "OS": "【内心独白】", "DIALOGUE": ""}.get(
                    dlg.get("type", "DIALOGUE"), ""
                )
                char = dlg.get("character", "")
                line = dlg.get("line", "")
                if type_tag:
                    lines.append(f"   {type_tag} {line}")
                else:
                    lines.append("   " + char + "：\u201c" + line + "\u201d")

        # 分镜方案
        if num in storyboard_idx:
            sb = storyboard_idx[num]
            lines.append(f"\n🖼️  分镜：{sb.get('shot_type', '')}")
            lines.append(f"   运镜：{sb.get('camera_movement', '')}")
            lines.append(f"   AI绘画Prompt：\n   {sb.get('image_prompt', '')}")
            if sb.get("visual_notes"):
                lines.append(f"   视觉备注：{sb['visual_notes']}")

        # 音效方案
        if num in sound_idx:
            sd = sound_idx[num]
            lines.append(f"\n🎵 音效：")
            lines.append(f"   环境音：{sd.get('ambience', '')}")
            lines.append(f"   动作音效：{sd.get('foley', '')}")
            lines.append(f"   BGM方向：{sd.get('bgm_mood', '')}")

        # 视觉备忘录
        if scene.get("visual_hint"):
            lines.append(f"\n💡 视觉备忘录：{scene['visual_hint']}")

    lines.append(f"\n{'=' * 60}")
    lines.append(f"剧本生成完毕，共 {len(screenplay_scenes)} 个场景")
    lines.append("=" * 60)

    return "\n".join(lines)
