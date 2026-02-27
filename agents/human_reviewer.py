"""
agents/human_reviewer.py
──────────────────────────
人工审核节点：在导演自动审核之前增加真人把关环节。

通过 HUMAN_REVIEW=true 环境变量开启。
关闭时（默认），此节点直接透传 → 导演审核，不影响自动流程。

人工审核界面展示：
  - 当前草稿的场景预览（编剧/分镜/音效各抽取第一个场景展示）
  - 角色档案摘要
  - 操作菜单：直接通过 / 给指定 Agent 提意见

设计原则：
  - 人工审核只在"第一轮完成后"弹出（skip_human_review=False 时）
  - 一旦人工给出意见并触发修改，skip_human_review 设为 True
  - 后续导演打回循环不再经过人工审核
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from state import WorkflowState, DirectorFeedback
from config import HUMAN_REVIEW

# 尝试使用 rich 美化输出
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt, Confirm
    from rich.table import Table
    from rich import box

    RICH_AVAILABLE = True
    console = Console()
except ImportError:
    RICH_AVAILABLE = False
    console = None


def _display_draft_preview(state: WorkflowState):
    """展示当前草稿的精简预览（各 Agent 的第一个场景）"""
    screenplay = state.get("screenplay_scenes", [])
    storyboard = state.get("storyboard_scenes", [])
    sound = state.get("sound_scenes", [])
    sheet = state.get("character_sheet")

    if RICH_AVAILABLE:
        # ── 角色档案摘要 ────────────────────────────────────────────
        if sheet and sheet.get("main_characters"):
            chars_text = "  ".join(
                f"[bold]{c.get('name', '')}[/bold]（{c.get('role', '')}）"
                for c in sheet["main_characters"]
            )
            console.print(
                Panel(chars_text, title="📚 识别到的角色", border_style="blue")
            )

        # ── 编剧第一场景 ─────────────────────────────────────────────
        if screenplay:
            s = screenplay[0]
            lines = [
                f"[bold]场景 {s.get('scene_number', '?')}[/bold]  {s.get('setting', '')}"
            ]
            lines.append(f"动作：{s.get('action', '')[:80]}")
            for d in (s.get("dialogue") or [])[:3]:
                tag = {"VO": "【旁白】", "OS": "【OS独白】"}.get(d.get("type", ""), "")
                lines.append(
                    f"  {tag}{d.get('character', '')}：{d.get('line', '')[:60]}"
                )
            console.print(
                Panel(
                    "\n".join(lines),
                    title="✍️  编剧（第一场节选）",
                    border_style="green",
                )
            )

        # ── 分镜第一条 Prompt ────────────────────────────────────────
        if storyboard:
            sb = storyboard[0]
            prompt_preview = sb.get("image_prompt", "")[:120]
            lines = [
                f"[bold]景别[/bold]：{sb.get('shot_type', '')}",
                f"[bold]运镜[/bold]：{sb.get('camera_movement', '')}",
                f"[bold]Prompt[/bold]：{prompt_preview}...",
            ]
            console.print(
                Panel(
                    "\n".join(lines),
                    title="🖼️  分镜师（第一场节选）",
                    border_style="yellow",
                )
            )

        # ── 音效第一场 ──────────────────────────────────────────────
        if sound:
            sd = sound[0]
            lines = [
                f"[bold]环境音[/bold]：{sd.get('ambience', '')[:60]}",
                f"[bold]音效[/bold]：{sd.get('foley', '')[:60]}",
                f"[bold]BGM[/bold]：{sd.get('bgm_mood', '')[:80]}",
            ]
            console.print(
                Panel(
                    "\n".join(lines),
                    title="🎵 音效师（第一场节选）",
                    border_style="magenta",
                )
            )
    else:
        # 纯文本输出
        print("\n" + "─" * 50)
        print("📋 当前草稿预览")
        if screenplay:
            s = screenplay[0]
            print(f"\n[编剧·场景{s.get('scene_number', '?')}] {s.get('setting', '')}")
            print(f"动作：{s.get('action', '')[:80]}")
        if storyboard:
            sb = storyboard[0]
            print(
                f"\n[分镜·场景{sb.get('scene_number', '?')}] 景别：{sb.get('shot_type', '')}"
            )
            print(f"Prompt：{sb.get('image_prompt', '')[:100]}")
        if sound:
            sd = sound[0]
            print(
                f"\n[音效·场景{sd.get('scene_number', '?')}] BGM：{sd.get('bgm_mood', '')[:80]}"
            )
        print("─" * 50)


def _get_user_decision(state: WorkflowState) -> tuple[str, list[DirectorFeedback]]:
    """
    交互式菜单，让用户决定下一步。

    Returns:
        (target, feedbacks)
        target: "director" / "screenwriter" / "storyboard" / "sound_designer"
        feedbacks: 若有的话
    """
    if RICH_AVAILABLE:
        console.print("\n[bold cyan]📝 请选择操作：[/bold cyan]")
        console.print("  [green][0][/green] 满意！直接交给导演审核")
        console.print("  [yellow][1][/yellow] 给编剧提意见（剧情/台词/旁白）")
        console.print("  [yellow][2][/yellow] 给分镜师提意见（画面/镜头）")
        console.print("  [yellow][3][/yellow] 给音效师提意见（声音/BGM）")

        choice = Prompt.ask("请输入", choices=["0", "1", "2", "3"], default="0")
    else:
        print("\n📝 请选择操作：")
        print("  [0] 满意！直接交给导演审核")
        print("  [1] 给编剧提意见")
        print("  [2] 给分镜师提意见")
        print("  [3] 给音效师提意见")
        choice = input("请输入 (0/1/2/3，默认0)：").strip() or "0"

    if choice == "0":
        return "director", []

    target_map = {"1": "screenwriter", "2": "storyboard", "3": "sound_designer"}
    target = target_map.get(choice, "director")
    target_name = {
        "screenwriter": "编剧",
        "storyboard": "分镜师",
        "sound_designer": "音效师",
    }.get(target, target)

    if RICH_AVAILABLE:
        issue = Prompt.ask(f"\n[yellow]请描述问题（针对{target_name}）[/yellow]")
        instruction = Prompt.ask(f"[yellow]请给出修改指令[/yellow]")
        scene_no_str = Prompt.ask("针对哪个场景？（全局问题输入 -1）", default="-1")
    else:
        print(f"\n针对{target_name}的意见：")
        issue = input("请描述问题：").strip()
        instruction = input("请给出修改指令：").strip()
        scene_no_str = input("针对哪个场景？（全局问题输入 -1）：").strip() or "-1"

    try:
        scene_no = int(scene_no_str)
    except ValueError:
        scene_no = -1

    feedback: DirectorFeedback = {
        "target_agent": target,
        "scene_number": scene_no,
        "issue": issue,
        "instruction": instruction,
    }
    return target, [feedback]


def human_reviewer_node(state: WorkflowState) -> dict:
    """
    LangGraph 节点函数：人工审核 Agent

    若 HUMAN_REVIEW=false（默认）或 skip_human_review=True，自动跳过。
    否则展示预览、等待用户输入决策。
    """
    if not HUMAN_REVIEW:
        # 静默跳过
        return {
            "human_review_target": "director",
            "skip_human_review": False,
        }

    if state.get("skip_human_review", False):
        # 已经审核过一次，此后跳过
        if RICH_AVAILABLE:
            console.print("  [dim]👤 人工审核 — 已跳过（修改后自动继续）[/dim]")
        else:
            print("  👤 人工审核 — 已跳过（修改后自动继续）")
        return {
            "human_review_target": "director",
            "skip_human_review": True,
        }

    # ── 显示预览并获取决策 ──────────────────────────────────────────
    if RICH_AVAILABLE:
        console.print(
            Panel(
                "[bold]📋 三位 Agent 的初稿已完成，请人工审核。[/bold]\n"
                "你可以直接通过，或向某个 Agent 提出修改意见。",
                title="👤 人工审核节点",
                border_style="cyan",
            )
        )
    else:
        print("\n" + "=" * 50)
        print("👤 人工审核节点")
        print("三位 Agent 的初稿已完成，请人工审核。")

    _display_draft_preview(state)

    target, feedbacks = _get_user_decision(state)

    if target == "director":
        if RICH_AVAILABLE:
            console.print("[green]✅ 人工审核通过，交给导演！[/green]\n")
        else:
            print("✅ 人工审核通过，交给导演！")
        return {
            "human_review_target": "director",
            "skip_human_review": False,  # 不需要 skip，因为通过了
            "director_feedback": [],
        }
    else:
        target_name = {
            "screenwriter": "编剧",
            "storyboard": "分镜师",
            "sound_designer": "音效师",
        }.get(target, target)
        if RICH_AVAILABLE:
            console.print(
                f"[yellow]🔄 已将意见转达给{target_name}，等待修改...[/yellow]\n"
            )
        else:
            print(f"🔄 已将意见转达给{target_name}，等待修改...")
        return {
            "human_review_target": target,
            "skip_human_review": True,  # 修改后跳过下次人工审核
            "director_feedback": feedbacks,
        }
