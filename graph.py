"""
graph.py (v2)
──────────────
LangGraph 图定义：包含所有节点、边和路由逻辑

v2 新增节点：
  - character_extractor：工作流第一步，提取角色档案
  - human_reviewer：在导演审核前的可选人工检查节点

完整工作流：
  ┌──────────────────────────────────────────────────────────────┐
  │ START                                                         │
  │   ↓                                                           │
  │ 📚 character_extractor  （仅运行一次，提取角色档案）              │
  │   ↓                                                           │
  │ ✍️  screenwriter  ◄──────────────────────────────────┐       │
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
  │                     (导演通过) ───→ END                         │
  └──────────────────────────────────────────────────────────────┘
"""

from langgraph.graph import StateGraph, END

from state import WorkflowState
from agents.character_extractor import character_extractor_node
from agents.screenwriter import screenwriter_node
from agents.storyboard import storyboard_node
from agents.sound_designer import sound_designer_node
from agents.human_reviewer import human_reviewer_node
from agents.director import director_node
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
    导演节点后的路由：通过则结束，退回则找对应 Agent。
    退回时 skip_human_review 已为 True（revision_count > 0），
    所以 sound_designer → director 会直接走，不再弹人工审核。
    """
    target = state.get("revision_target", "approved")
    if target == "approved":
        return "end"
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
    workflow.add_node("character_extractor", character_extractor_node)
    workflow.add_node("screenwriter", screenwriter_node)
    workflow.add_node("storyboard", storyboard_node)
    workflow.add_node("sound_designer", sound_designer_node)
    workflow.add_node("human_reviewer", human_reviewer_node)
    workflow.add_node("director", director_node)

    # ── 入口：角色提取是第一步 ────────────────────────────────────────────────
    workflow.set_entry_point("character_extractor")

    # ── 固定边（线性流程） ────────────────────────────────────────────────────
    workflow.add_edge("character_extractor", "screenwriter")
    workflow.add_edge("screenwriter", "storyboard")
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
            "screenwriter": "screenwriter",
            "storyboard": "storyboard",
            "sound_designer": "sound_designer",
        },
    )

    # ── 导演后：条件边（通过/打回）──────────────────────────────────────────
    workflow.add_conditional_edges(
        "director",
        route_after_director,
        {
            "end": END,
            "screenwriter": "screenwriter",
            "storyboard": "storyboard",
            "sound_designer": "sound_designer",
        },
    )

    return workflow.compile()


_compiled_workflow = None


def get_workflow():
    """获取编译好的工作流（单例）"""
    global _compiled_workflow
    if _compiled_workflow is None:
        _compiled_workflow = build_workflow()
    return _compiled_workflow
