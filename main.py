"""
main.py (v2)
─────────────
程序入口：整合了长文本分段、进度可视化、人工审核开关

新功能（v2）：
  - 长文本自动分段：超过 CHUNK_SIZE 字符的输入会自动分段处理
  - 进度可视化：rich 美化输出，展示每个 Agent 状态和用时
  - 多段合并：多个 chunk 的场景编号自动偏移，最终合并为一份完整剧本

用法：
    python main.py
    python main.py --input my_novel.txt --type 古代言情
    HUMAN_REVIEW=true python main.py      # 开启人工审核
    CHUNK_SIZE=1500 python main.py        # 调小分段大小（测试用）
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import (
    SUPPORTED_NOVEL_TYPES,
    MAX_REVISIONS,
    LLM_PROVIDER,
    LLM_MODEL,
    DEBUG,
    HUMAN_REVIEW,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    SUPPORTED_IMAGE_STYLES,
)
from graph import get_workflow
from state import WorkflowState
from utils.chunker import split_into_chunks, get_chunk_info
from utils.progress import progress


def load_novel_text(filepath: str) -> str:
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"找不到文件: {filepath}")
    return path.read_text(encoding="utf-8")


def validate_env():
    if LLM_PROVIDER == "openai":
        if not os.getenv("OPENAI_API_KEY", ""):
            print("⚠️  未检测到 OPENAI_API_KEY")
            print("   export OPENAI_API_KEY=sk-your-key")
            sys.exit(1)
    elif LLM_PROVIDER == "gemini":
        if not os.getenv("GOOGLE_API_KEY", ""):
            print("⚠️  未检测到 GOOGLE_API_KEY")
            print("   export GOOGLE_API_KEY=your-key")
            sys.exit(1)


def build_initial_state(novel_text: str, novel_type: str) -> WorkflowState:
    """构建工作流初始状态"""
    return {
        "novel_text": novel_text,
        "novel_type": novel_type,
        "character_sheet": None,
        "screenplay_scenes": [],
        "storyboard_scenes": [],
        "sound_scenes": [],
        "director_feedback": [],
        "revision_target": None,
        "revision_count": 0,
        "skip_human_review": False,
        "human_review_target": "director",
        "is_approved": False,
        "final_script": None,
    }


def run_single_chunk(
    novel_text: str, novel_type: str, scene_offset: int = 0
) -> WorkflowState:
    """
    对单个文本 chunk 运行完整的多智能体工作流。

    Args:
        novel_text: 要处理的文本片段
        novel_type: 小说类型
        scene_offset: 场景编号偏移（多段处理时保证编号连续）

    Returns:
        最终的 WorkflowState
    """
    initial_state = build_initial_state(novel_text, novel_type)
    workflow = get_workflow()
    final_state = workflow.invoke(initial_state)

    # 应用场景编号偏移（多段合并时保证连续）
    if scene_offset > 0:
        for scene_list_key in [
            "screenplay_scenes",
            "storyboard_scenes",
            "sound_scenes",
        ]:
            for scene in final_state.get(scene_list_key, []):
                scene["scene_number"] = scene["scene_number"] + scene_offset

    return final_state


def merge_chunk_results(
    chunk_states: list[WorkflowState], novel_type: str
) -> WorkflowState:
    """
    将多个 chunk 的工作流状态合并为一个完整状态，
    重新生成最终剧本文本。
    """
    from agents.director import _format_final_script

    merged: WorkflowState = {
        "novel_text": "\n\n".join(s.get("novel_text", "") for s in chunk_states),
        "novel_type": novel_type,
        "character_sheet": chunk_states[0].get("character_sheet")
        if chunk_states
        else None,
        "screenplay_scenes": [],
        "storyboard_scenes": [],
        "sound_scenes": [],
        "director_feedback": [],
        "revision_target": "approved",
        "revision_count": max(s.get("revision_count", 0) for s in chunk_states),
        "skip_human_review": True,
        "human_review_target": "director",
        "is_approved": True,
        "final_script": None,
    }

    for state in chunk_states:
        merged["screenplay_scenes"].extend(state.get("screenplay_scenes", []))
        merged["storyboard_scenes"].extend(state.get("storyboard_scenes", []))
        merged["sound_scenes"].extend(state.get("sound_scenes", []))

    # 重新生成完整剧本
    merged["final_script"] = _format_final_script(merged)
    return merged


def save_results(state: WorkflowState, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    script_path = output_dir / f"final_script_{timestamp}.txt"
    script_path.write_text(state.get("final_script", ""), encoding="utf-8")

    raw_data = {
        "novel_type": state.get("novel_type"),
        "character_sheet": state.get("character_sheet"),
        "screenplay_scenes": state.get("screenplay_scenes", []),
        "storyboard_scenes": state.get("storyboard_scenes", []),
        "sound_scenes": state.get("sound_scenes", []),
        "revision_count": state.get("revision_count", 0),
    }
    json_path = output_dir / f"raw_data_{timestamp}.json"
    json_path.write_text(
        json.dumps(raw_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return script_path


def main():
    parser = argparse.ArgumentParser(
        description="网文转漫剧剧本 · 多智能体工作流 v2",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", "-i", default="sample_input/chapter_1.txt")
    parser.add_argument(
        "--type", "-t", default="仙侠/玄幻", choices=SUPPORTED_NOVEL_TYPES
    )
    parser.add_argument(
        "--style", "-s", default="真人电影风格", 
        choices=list(SUPPORTED_IMAGE_STYLES.keys()),
        help="图片画风：真人电影风格 / 动漫风格 / 插画风格 / 3D渲染风格"
    )
    parser.add_argument("--output", "-o", default="./output")
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()

    # 设置图片风格（覆盖环境变量）
    import config
    config.IMAGE_STYLE_TYPE = args.style
    os.environ["IMAGE_STYLE_TYPE"] = args.style

    validate_env()

    try:
        novel_text = load_novel_text(args.input)
    except FileNotFoundError as e:
        print(f"❌ {e}")
        sys.exit(1)

    # ── 分析文本，决定是否分段 ────────────────────────────────────────────────
    info = get_chunk_info(novel_text, CHUNK_SIZE)
    chunks = split_into_chunks(novel_text, CHUNK_SIZE, CHUNK_OVERLAP)

    # ── 打印启动横幅 ──────────────────────────────────────────────────────────
    progress.print_banner(
        novel_type=args.type,
        novel_chars=info["total_chars"],
        llm_provider=LLM_PROVIDER,
        llm_model=LLM_MODEL,
        chunk_count=len(chunks),
        max_revisions=MAX_REVISIONS,
        image_style=args.style,
    )

    if len(chunks) > 1:
        print(
            f"\n📦 长文本模式：文本被分为 {len(chunks)} 段（每段约 {CHUNK_SIZE} 字符）"
        )
        print(f"   将依次处理每段，最终合并为完整剧本\n")

    if HUMAN_REVIEW:
        print("👤 人工审核模式已开启（第一轮完成后会暂停等待确认）\n")

    # ── 执行工作流 ────────────────────────────────────────────────────────────
    print("🚀 工作流启动...\n")
    chunk_states = []
    scene_offset = 0

    try:
        for i, chunk in enumerate(chunks):
            if len(chunks) > 1:
                print(f"\n{'━' * 50}")
                print(
                    f"  ▶ 处理第 {i + 1}/{len(chunks)} 段  "
                    f"（{len(chunk)} 字符，场景从 {scene_offset + 1} 开始）"
                )
                print(f"{'━' * 50}")

            state = run_single_chunk(chunk, args.type, scene_offset)
            chunk_states.append(state)

            # 更新下一段的场景偏移
            scene_count = len(state.get("screenplay_scenes", []))
            scene_offset += scene_count

    except KeyboardInterrupt:
        print("\n⚠️  用户中断")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ 工作流执行出错: {type(e).__name__}: {e}")
        if DEBUG:
            import traceback

            traceback.print_exc()
        sys.exit(1)

    # ── 合并多段结果（或直接使用单段结果） ────────────────────────────────────
    if len(chunk_states) == 1:
        final_state = chunk_states[0]
    else:
        print(f"\n🔗 合并 {len(chunks)} 段结果...")
        final_state = merge_chunk_results(chunk_states, args.type)

    total_scenes = len(final_state.get("screenplay_scenes", []))
    total_revisions = final_state.get("revision_count", 0)

    # ── 打印汇总 ──────────────────────────────────────────────────────────────
    chars = (final_state.get("character_sheet") or {}).get("main_characters", [])
    char_names = "、".join(c.get("name", "?") for c in chars) if chars else "无"
    print(f"\n{'=' * 55}")
    print(f"  ✅ 工作流完成")
    print(f"  📚 识别角色：{char_names}")
    print(f"  📝 总场景数：{total_scenes}")
    print(f"  🔄 审核轮次：{total_revisions}")

    # ── 打印最终剧本 ──────────────────────────────────────────────────────────
    print()
    print(final_state.get("final_script", "（无输出）"))

    # ── 保存文件 ──────────────────────────────────────────────────────────────
    if not args.no_save:
        script_path = save_results(final_state, Path(args.output))
        print(f"\n📄 最终剧本：{script_path}")
        print(f"📊 原始数据：{Path(args.output) / 'raw_data_*.json'}")


if __name__ == "__main__":
    main()
