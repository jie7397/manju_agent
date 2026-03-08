"""
graph.py (v5)
──────────────
LangGraph 图定义：包含所有节点、边和路由逻辑

v5 更新：
  - 新增 outline_extractor 作为入口节点
  - 大纲驱动的工作流，后续 agent 基于大纲工作

完整工作流：
  ┌──────────────────────────────────────────────────────────────┐
  │ START                                                         │
  │   ↓                                                           │
  │ 📋 outline_extractor  （提取大纲：核心角色、主线、分段）        │
  │   ↓                                                           │
  │ 👤 character_extractor  （基于大纲提取角色档案）               │
  │   ↓                                                           │
  │ ✍️  screenwriter  ◄──────────────────────────────────┐       │
  │   ↓                                                  │       │
  │ 🎨 production_designer  （提取场景，基于剧本）        │       │
  │   ↓                                                  │       │
  │ 🖼️  storyboard   ◄──────────────────────────┐       │       │
  │   ↓                                          │       │       │
  │ 🎵 sound_designer ◄──────────────┐           │       │       │
  │   ↓                              │           │       │       │
  │  [条件边：是否人工审核]            │           │       │       │
  │   ├─ HUMAN_REVIEW=true ──→ 👤 human_reviewer  │      │       │
  │   │                           │               │      │       │
  │   │   (human 打回某个 agent) ──┴───────────────┘      │       │
  │   │                                                    │       │
  │   └─ HUMAN_REVIEW=false 或已审过 ──→ 🎬 director        │       │
  │                                      │                 │       │
  │                          (导演打回) ──┘─────────────────┘       │
  │                                      │                          │
  │                     (导演通过) ───→ 🖼️ image_generator          │
  │                                            │                   │
  │                                            ↓                   │
  │                                           END                  │
  └──────────────────────────────────────────────────────────────┘
"""

from langgraph.graph import StateGraph, END

from state import WorkflowState
from agents.outline_extractor import outline_extractor_node
from agents.character_extractor import character_extractor_node
from agents.production_designer import production_designer_node
from agents.screenwriter import screenwriter_node
from agents.storyboard import storyboard_node
from agents.sound_designer import sound_designer_node
from agents.human_reviewer import human_reviewer_node
from agents.director import director_node
from agents.image_generator import image_generator_node
from config import HUMAN_REVIEW


# ──────────────────────────────────────────────────────────────────────────────
# 路由函数
# ──────────────────────────────────────────────────────────────────────────────


def route_after_sound_designer(state: WorkflowState) -> str:
    """
    音效师完成后的路由：决定是否进入人工审核。
      - HUMAN_REVIEW=false  → 直接去导演
      - skip_human_review=True → 直接去导演（已审核过一次）
      - 否则 → 进入人工审核节点
    """
    if not HUMAN_REVIEW or state.get("skip_human_review", False):
        return "director"
    return "human_reviewer"


def route_after_human_reviewer(state: WorkflowState) -> str:
    """
    人工审核节点后的路由，根据 human_review_target 决定下一步。
    """
    return state.get("human_review_target", "director")


def route_after_director(state: WorkflowState) -> str:
    """
    导演节点后的路由：通过则生成图片，退回则找对应 Agent。
    v4: 审核通过后进入 image_generator 节点生成图片。
    """
    target = state.get("revision_target", "approved")
    if target == "approved":
        return "image_generator"  # 审核通过，生成图片
    elif target == "character_extractor":
        return "character_extractor"
    elif target == "production_designer":
        return "production_designer"
    elif target == "screenwriter":
        return "screenwriter"
    elif target == "storyboard":
        return "storyboard"
    elif target == "sound_designer":
        return "sound_designer"
    else:
        return "screenwriter"


# ──────────────────────────────────────────────────────────────────────────────
# 图构建
# ──────────────────────────────────────────────────────────────────────────────


def build_workflow() -> StateGraph:
    """构建并编译完整的 LangGraph 工作流图"""
    workflow = StateGraph(WorkflowState)

    # ── 注册节点 ──────────────────────────────────────────────────────────────
    workflow.add_node("outline_extractor", outline_extractor_node)  # v5: 大纲提取器
    workflow.add_node("character_extractor", character_extractor_node)
    workflow.add_node("production_designer", production_designer_node)
    workflow.add_node("screenwriter", screenwriter_node)
    workflow.add_node("storyboard", storyboard_node)
    workflow.add_node("sound_designer", sound_designer_node)
    workflow.add_node("human_reviewer", human_reviewer_node)
    workflow.add_node("director", director_node)
    workflow.add_node("image_generator", image_generator_node)

    # ── 入口：大纲提取器是第一步 ──────────────────────────────────────────────
    workflow.set_entry_point("outline_extractor")

    # ── 固定边（线性流程）────────────────────────────────────────────────────
    # v5: 大纲提取 → 角色提取 → 编剧 → 美术指导 → ...
    workflow.add_edge("outline_extractor", "character_extractor")
    workflow.add_edge("character_extractor", "screenwriter")
    workflow.add_edge("screenwriter", "production_designer")
    workflow.add_edge("production_designer", "storyboard")
    workflow.add_edge("storyboard", "sound_designer")

    # ── 音效师后：条件边（是否走人工审核）────────────────────────────────────
    workflow.add_conditional_edges(
        "sound_designer",
        route_after_sound_designer,
        {
            "human_reviewer": "human_reviewer",
            "director": "director",
        },
    )

    # ── 人工审核后：条件边（通过/退回指定 Agent）─────────────────────────────
    workflow.add_conditional_edges(
        "human_reviewer",
        route_after_human_reviewer,
        {
            "director": "director",
            "character_extractor": "character_extractor",
            "production_designer": "production_designer",
            "screenwriter": "screenwriter",
            "storyboard": "storyboard",
            "sound_designer": "sound_designer",
        },
    )

    # ── 导演后：条件边（通过→生成图片 / 打回）───────────────────────────────
    workflow.add_conditional_edges(
        "director",
        route_after_director,
        {
            "image_generator": "image_generator",  # v4: 审核通过后生成图片
            "character_extractor": "character_extractor",
            "production_designer": "production_designer",
            "screenwriter": "screenwriter",
            "storyboard": "storyboard",
            "sound_designer": "sound_designer",
        },
    )

    # ── 图片生成后：结束 ─────────────────────────────────────────────────────
    workflow.add_edge("image_generator", END)

    return workflow.compile()


_compiled_workflow = None


def get_workflow():
    """获取编译好的工作流（单例）"""
    global _compiled_workflow
    if _compiled_workflow is None:
        _compiled_workflow = build_workflow()
    return _compiled_workflow
