"""
utils/progress.py
──────────────────
进度可视化工具（基于 rich 库）。

提供：
  1. WorkflowProgress 类：跟踪各 Agent 的运行状态
  2. 每个 Agent 开始/完成的美观打印
  3. 最终汇总表格

依赖 rich 库（pip install rich），若未安装则降级为普通 print。
"""

import time
from typing import Optional

# 尝试导入 rich，不可用则降级
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
    from rich.columns import Columns
    from rich import box

    RICH_AVAILABLE = True
    console = Console()
except ImportError:
    RICH_AVAILABLE = False
    console = None


# Agent 的元信息（展示用）
AGENT_META = {
    "character_extractor": ("📚", "角色提取", "提取角色档案和世界观色调"),
    "screenwriter": ("✍️ ", "编剧", "提炼对白、旁白、场景描写"),
    "storyboard": ("🖼️ ", "分镜师", "生成 AI 绘画 Prompt"),
    "sound_designer": ("🎵", "音效师", "设计三层声音方案"),
    "human_reviewer": ("👤", "人工审核", "人工检查并决策"),
    "director": ("🎬", "导演", "四维质量审核"),
}


class WorkflowProgress:
    """工作流进度追踪器（单例使用）"""

    def __init__(self):
        self._start_time = time.time()
        self._agent_status: dict[str, str] = {}  # agent_id → status
        self._agent_result: dict[str, str] = {}  # agent_id → 结果摘要
        self._agent_times: dict[str, float] = {}  # agent_id → 用时(秒)
        self._agent_start: dict[str, float] = {}  # agent_id → 开始时间

    def start(self, agent_id: str):
        """标记某个 Agent 开始运行"""
        self._agent_status[agent_id] = "running"
        self._agent_start[agent_id] = time.time()

        if RICH_AVAILABLE:
            emoji, name, desc = AGENT_META.get(agent_id, ("🤖", agent_id, ""))
            console.rule(f"[bold cyan]{emoji}  {name}[/bold cyan]  [dim]{desc}[/dim]")
        else:
            emoji, name, _ = AGENT_META.get(agent_id, ("🤖", agent_id, ""))
            print(f"\n{'─' * 50}")
            print(f"{emoji} [{name}] 开始工作...")

    def done(self, agent_id: str, result_summary: str = ""):
        """标记某个 Agent 完成"""
        elapsed = time.time() - self._agent_start.get(agent_id, time.time())
        self._agent_status[agent_id] = "done"
        self._agent_result[agent_id] = result_summary
        self._agent_times[agent_id] = elapsed

        if RICH_AVAILABLE:
            emoji, name, _ = AGENT_META.get(agent_id, ("🤖", agent_id, ""))
            console.print(
                f"  [green]✅ {emoji} {name} 完成[/green]  "
                f"[dim]{result_summary}  ({elapsed:.1f}s)[/dim]"
            )
        else:
            emoji, name, _ = AGENT_META.get(agent_id, ("🤖", agent_id, ""))
            print(f"  ✅ {emoji} [{name}] 完成  {result_summary}  ({elapsed:.1f}s)")

    def skip(self, agent_id: str, reason: str = ""):
        """标记某个 Agent 被跳过（如 HUMAN_REVIEW=false）"""
        self._agent_status[agent_id] = "skipped"
        self._agent_result[agent_id] = reason

        if RICH_AVAILABLE:
            emoji, name, _ = AGENT_META.get(agent_id, ("🤖", agent_id, ""))
            console.print(f"  [dim]⏭️  {emoji} {name} 已跳过  {reason}[/dim]")
        else:
            emoji, name, _ = AGENT_META.get(agent_id, ("🤖", agent_id, ""))
            print(f"  ⏭️  [{name}] 已跳过  {reason}")

    def revise(self, agent_id: str, reason: str = ""):
        """标记某个 Agent 被打回重做"""
        self._agent_status[agent_id] = "revising"

        if RICH_AVAILABLE:
            emoji, name, _ = AGENT_META.get(agent_id, ("🤖", agent_id, ""))
            console.print(
                f"  [yellow]🔄 {emoji} {name} 退回重做[/yellow]  [dim]{reason}[/dim]"
            )
        else:
            emoji, name, _ = AGENT_META.get(agent_id, ("🤖", agent_id, ""))
            print(f"  🔄 [{name}] 退回重做  {reason}")

    def print_banner(
        self,
        novel_type: str,
        novel_chars: int,
        llm_provider: str,
        llm_model: str,
        chunk_count: int = 1,
        max_revisions: int = 3,
    ):
        """打印工作流启动横幅"""
        if RICH_AVAILABLE:
            content = (
                f"[bold]小说类型[/bold]：{novel_type}\n"
                f"[bold]文本长度[/bold]：{novel_chars:,} 字符"
                + (
                    f"  →  自动分 [bold cyan]{chunk_count}[/bold cyan] 个片段处理"
                    if chunk_count > 1
                    else ""
                )
                + "\n"
                f"[bold]LLM[/bold]：{llm_provider} / {llm_model}\n"
                f"[bold]最大审核轮数[/bold]：{max_revisions}"
            )
            console.print(
                Panel(
                    content,
                    title="[bold magenta]🎬 网文转漫剧 · 多智能体工作流 v2[/bold magenta]",
                    border_style="magenta",
                    expand=False,
                )
            )
        else:
            print("╔══════════════════════════════════════════════╗")
            print("║    🎬 网文转漫剧 · 多智能体工作流 v2         ║")
            print("╚══════════════════════════════════════════════╝")
            print(f"  小说类型：{novel_type}")
            print(
                f"  文本长度：{novel_chars:,} 字符"
                + (f"  →  分 {chunk_count} 段处理" if chunk_count > 1 else "")
            )
            print(f"  LLM：{llm_provider} / {llm_model}")

    def print_summary(
        self,
        is_approved: bool,
        revision_count: int,
        scene_count: int,
        output_path: Optional[str] = None,
    ):
        """打印最终汇总"""
        total_time = time.time() - self._start_time

        if RICH_AVAILABLE:
            table = Table(
                title="📊 工作流执行摘要",
                box=box.ROUNDED,
                show_header=True,
                header_style="bold cyan",
            )
            table.add_column("Agent", style="bold")
            table.add_column("状态", justify="center")
            table.add_column("结果", style="dim")
            table.add_column("用时", justify="right", style="dim")

            for agent_id, (emoji, name, _) in AGENT_META.items():
                status = self._agent_status.get(agent_id, "not_run")
                result = self._agent_result.get(agent_id, "-")
                elapsed = self._agent_times.get(agent_id, 0)

                status_display = {
                    "done": "[green]✅ 完成[/green]",
                    "skipped": "[dim]⏭️  跳过[/dim]",
                    "revising": "[yellow]🔄 重做[/yellow]",
                    "running": "[blue]🔄 运行中[/blue]",
                    "not_run": "[dim]─[/dim]",
                }.get(status, status)

                table.add_row(
                    f"{emoji} {name}",
                    status_display,
                    result[:40] + "..." if len(result) > 40 else result,
                    f"{elapsed:.1f}s" if elapsed > 0 else "-",
                )

            console.print(table)
            console.print(
                f"\n[bold green]✅ 工作流完成！[/bold green]  "
                f"审核 {revision_count} 轮 | {scene_count} 场景 | "
                f"总用时 {total_time:.1f}s"
            )
            if output_path:
                console.print(f"[dim]📄 剧本已保存：{output_path}[/dim]")
        else:
            print(f"\n{'=' * 50}")
            print(f"✅ 工作流完成！审核 {revision_count} 轮 | {scene_count} 场景")
            print(f"总用时：{total_time:.1f}s")
            if output_path:
                print(f"📄 剧本已保存：{output_path}")


# 全局进度实例（在 graph.py 中的节点函数里直接使用）
progress = WorkflowProgress()
