"""
agents/outline_extractor.py
──────────────────────────────
大纲提取器 Agent：从小说文本中提取故事大纲

v2 更新：
  - 支持超长文本分段处理
  - 三步流程：识别章节 → 批量摘要 → 合并大纲

职责：
  - 快速扫描全文，提取核心角色
  - 生成主线剧情摘要
  - 识别关键场景
  - 按剧情节点划分段落

输出：
  - story_outline: 包含核心角色、主线摘要、关键场景、分段规划
"""

import os
import re
import sys
import json
import time
from pathlib import Path
from datetime import datetime
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from state import WorkflowState, StoryOutline
from config import DEBUG


def _save_outline_to_file(outline: dict, summaries: List[dict] = None):
    """保存大纲到文件"""
    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 保存完整大纲 JSON
    outline_file = output_dir / f"story_outline_{timestamp}.json"
    with open(outline_file, "w", encoding="utf-8") as f:
        json.dump(outline, f, ensure_ascii=False, indent=2)
    print(f"  📝 大纲已保存: {outline_file}")
    
    # 保存章节摘要
    if summaries:
        summaries_file = output_dir / f"chapter_summaries_{timestamp}.json"
        with open(summaries_file, "w", encoding="utf-8") as f:
            json.dump(summaries, f, ensure_ascii=False, indent=2)
        print(f"  📄 章节摘要已保存: {summaries_file}")
    
    # 保存纯文本版本
    txt_file = output_dir / f"story_outline_{timestamp}.txt"
    with open(txt_file, "w", encoding="utf-8") as f:
        f.write("=" * 60 + "\n")
        f.write(f"故事大纲 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 60 + "\n\n")
        
        f.write(f"【标题】{outline.get('title', '未知')}\n")
        f.write(f"【类型】{outline.get('genre', '未知')}\n\n")
        
        f.write("【核心角色】\n")
        for char in outline.get('core_characters', []):
            importance = "★" * char.get('importance', 1)
            f.write(f"  • {char.get('name')} ({char.get('role')}) {importance}\n")
            f.write(f"    {char.get('brief_description', '')}\n")
        f.write("\n")
        
        f.write("【主线摘要】\n")
        f.write(f"{outline.get('main_plot_summary', '')}\n\n")
        
        f.write("【关键场景】\n")
        for scene in outline.get('key_scenes', []):
            f.write(f"  • {scene}\n")
        f.write("\n")
        
        f.write("【剧情分段】\n")
        for seg in outline.get('chapter_segments', []):
            f.write(f"\n  [{seg.get('chapters')}] {seg.get('theme')}\n")
            f.write(f"  角色: {', '.join(seg.get('core_characters', []))}\n")
            f.write(f"  {seg.get('summary', '')}\n")
    
    print(f"  📄 文本版本: {txt_file}")

# LLM 服务
try:
    from services.llm import ArkLLMService
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False


# ──────────────────────────────────────────────────────────────────────────────
# 配置
# ──────────────────────────────────────────────────────────────────────────────

# 章节分组大小（每组处理多少章）
CHAPTER_GROUP_SIZE = 10

# 每段最大字符数
MAX_CHARS_PER_GROUP = 15000

# LLM 调用间隔（秒），避免频率限制
LLM_CALL_INTERVAL = 0.5

# LLM 调用超时（秒）
LLM_TIMEOUT = 120

# 断点续传文件
CHECKPOINT_FILE = "output/outline_checkpoint.json"


# ──────────────────────────────────────────────────────────────────────────────
# Prompt 加载
# ──────────────────────────────────────────────────────────────────────────────

def _load_prompt() -> str:
    """加载大纲提取器的 prompt"""
    prompt_path = Path(__file__).parent.parent / "prompts" / "outline_extractor_prompt.md"
    if prompt_path.exists():
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()
    return ""


# ──────────────────────────────────────────────────────────────────────────────
# 章节处理
# ──────────────────────────────────────────────────────────────────────────────

def _split_into_chapters(text: str) -> List[dict]:
    """
    将文本按章节切分
    
    Returns:
        [{"chapter": "第1章 xxx", "content": "...", "start": 0, "end": 100}, ...]
    """
    # 匹配章节标题：第X章 或 第XX章
    chapter_pattern = r"第[一二三四五六七八九十百千万零\d]+章[^\n]*"
    
    # 找到所有章节标题的位置
    matches = list(re.finditer(chapter_pattern, text))
    
    if not matches:
        # 没有识别到章节，按固定字符数分段
        print("  [Info] 未识别到章节标题，按固定字符数分段")
        return _split_by_chars(text)
    
    chapters = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chapter_title = match.group().strip()
        content = text[start:end]
        
        chapters.append({
            "chapter": chapter_title,
            "content": content,
            "start": start,
            "end": end,
            "char_count": len(content)
        })
    
    print(f"  [Info] 识别到 {len(chapters)} 个章节")
    return chapters


def _split_by_chars(text: str, chunk_size: int = MAX_CHARS_PER_GROUP) -> List[dict]:
    """按固定字符数分段"""
    chunks = []
    total_chars = len(text)
    
    for i in range(0, total_chars, chunk_size):
        end = min(i + chunk_size, total_chars)
        chunks.append({
            "chapter": f"第{i//chunk_size + 1}段",
            "content": text[i:end],
            "start": i,
            "end": end,
            "char_count": end - i
        })
    
    return chunks


def _group_chapters(chapters: List[dict], group_size: int = CHAPTER_GROUP_SIZE) -> List[dict]:
    """
    将章节分组，每组约 10 章
    
    Returns:
        [{"group_id": 1, "chapters": "1-10", "content": "...", "summary": None}, ...]
    """
    groups = []
    
    for i in range(0, len(chapters), group_size):
        group_chapters = chapters[i:i + group_size]
        
        # 合并章节内容
        content = "\n\n".join([c["content"] for c in group_chapters])
        
        # 如果内容太长，截断
        if len(content) > MAX_CHARS_PER_GROUP * 2:
            content = content[:MAX_CHARS_PER_GROUP * 2]
        
        # 提取章节范围
        first_chapter = group_chapters[0]["chapter"]
        last_chapter = group_chapters[-1]["chapter"]
        
        # 提取章节编号
        first_num = _extract_chapter_number(first_chapter)
        last_num = _extract_chapter_number(last_chapter)
        
        if first_num and last_num:
            chapters_range = f"{first_num}-{last_num}"
        else:
            chapters_range = f"{i+1}-{min(i+group_size, len(chapters))}"
        
        groups.append({
            "group_id": i // group_size + 1,
            "chapters": chapters_range,
            "content": content,
            "char_count": len(content),
            "summary": None
        })
    
    return groups


def _extract_chapter_number(chapter_title: str) -> Optional[int]:
    """从章节标题中提取章节号"""
    # 匹配数字
    match = re.search(r"第(\d+)章", chapter_title)
    if match:
        return int(match.group(1))
    
    # 匹配中文数字
    cn_nums = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
               "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    match = re.search(r"第([一二三四五六七八九十]+)章", chapter_title)
    if match:
        cn_str = match.group(1)
        if cn_str in cn_nums:
            return cn_nums[cn_str]
    
    return None


# ──────────────────────────────────────────────────────────────────────────────
# LLM 调用
# ──────────────────────────────────────────────────────────────────────────────

def _save_checkpoint(summaries: List[dict], current_group: int, total_groups: int):
    """保存断点续传文件"""
    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    checkpoint = {
        "timestamp": datetime.now().isoformat(),
        "current_group": current_group,
        "total_groups": total_groups,
        "summaries": summaries
    }
    
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(checkpoint, f, ensure_ascii=False, indent=2)
    print(f"    💾 断点已保存 (进度: {current_group}/{total_groups})", flush=True)


def _load_checkpoint() -> Optional[dict]:
    """加载断点续传文件"""
    if Path(CHECKPOINT_FILE).exists():
        try:
            with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return None
    return None


def _clear_checkpoint():
    """清除断点文件"""
    if Path(CHECKPOINT_FILE).exists():
        Path(CHECKPOINT_FILE).unlink()


def _extract_chapter_group_summary(group: dict, llm_service: ArkLLMService, progress_file=None) -> dict:
    """
    提取一组章节的摘要（带超时处理）
    """
    print(f"    正在提取第 {group['chapters']} 章摘要...", flush=True)
    
    prompt = f"""请分析以下章节内容，提取关键信息：

章节范围：第 {group['chapters']} 章

内容：
{group['content'][:MAX_CHARS_PER_GROUP]}

请输出 JSON 格式：
{{
    "chapters": "{group['chapters']}",
    "summary": "这组章节的主要内容摘要（100-200字）",
    "key_events": ["关键事件1", "关键事件2", ...],
    "characters": ["出场角色1", "出场角色2", ...],
    "scenes": ["场景1", "场景2", ...]
}}
"""
    
    try:
        response = llm_service.generate_text(
            system_prompt="你是一位资深文学编辑，擅长提炼小说章节摘要。",
            user_prompt=prompt,
            temperature=0.3,
        )
        
        # 解析 JSON
        json_str = response.strip()
        if "```json" in json_str:
            start = json_str.find("```json") + 7
            end = json_str.find("```", start)
            json_str = json_str[start:end].strip()
        elif "```" in json_str:
            start = json_str.find("```") + 3
            end = json_str.find("```", start)
            json_str = json_str[start:end].strip()
        
        result = json.loads(json_str)
        return result
        
    except Exception as e:
        print(f"    ⚠️ 章节 {group['chapters']} 摘要提取失败: {e}")
        return {
            "chapters": group['chapters'],
            "summary": "摘要提取失败",
            "key_events": [],
            "characters": [],
            "scenes": []
        }


def _merge_summaries_to_outline(summaries: List[dict], llm_service: ArkLLMService) -> dict:
    """
    将所有章节摘要合并成完整大纲
    """
    # 构建摘要文本
    summaries_text = "\n\n".join([
        f"【第{s['chapters']}章】\n{s['summary']}\n角色：{', '.join(s.get('characters', []))}\n场景：{', '.join(s.get('scenes', []))}"
        for s in summaries
    ])
    
    prompt = f"""请根据以下章节摘要，生成完整的故事大纲：

{summaries_text}

请输出 JSON 格式：
{{
    "title": "故事标题",
    "genre": "类型",
    "core_characters": [
        {{"name": "角色名", "role": "主角/配角", "importance": 5, "brief_description": "描述"}}
    ],
    "main_plot_summary": "主线剧情摘要（200-500字）",
    "key_scenes": ["关键场景1", "关键场景2", ...],
    "chapter_segments": [
        {{
            "segment_id": 1,
            "chapters": "1-10",
            "theme": "主题",
            "core_characters": ["角色1", "角色2"],
            "summary": "段落摘要"
        }}
    ]
}}

注意：
1. core_characters 只保留重要性 3 及以上的核心角色（5-10人）
2. main_plot_summary 要简洁，突出主线
3. chapter_segments 按剧情节点划分，不是简单按章节
"""
    
    try:
        response = llm_service.generate_text(
            system_prompt="你是一位资深文学编辑，擅长提炼故事大纲。",
            user_prompt=prompt,
            temperature=0.3,
        )
        
        # 解析 JSON
        json_str = response.strip()
        if "```json" in json_str:
            start = json_str.find("```json") + 7
            end = json_str.find("```", start)
            json_str = json_str[start:end].strip()
        elif "```" in json_str:
            start = json_str.find("```") + 3
            end = json_str.find("```", start)
            json_str = json_str[start:end].strip()
        
        outline = json.loads(json_str)
        return outline
        
    except Exception as e:
        print(f"  ⚠️ 大纲合并失败: {e}")
        return _get_default_outline()


# ──────────────────────────────────────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────────────────────────────────────

def _get_default_outline() -> dict:
    """返回默认的空大纲结构"""
    return {
        "title": "未知标题",
        "genre": "未知",
        "core_characters": [],
        "main_plot_summary": "无法提取剧情摘要",
        "key_scenes": [],
        "chapter_segments": []
    }


def _extract_outline_with_llm(text: str, llm_service: ArkLLMService) -> tuple:
    """
    使用 LLM 提取故事大纲（支持分段处理和断点续传）
    
    Returns:
        (outline, summaries)
    """
    text_len = len(text)
    print(f"  [Info] 文本长度: {text_len} 字符", flush=True)
    
    # 判断是否需要分段处理
    if text_len <= MAX_CHARS_PER_GROUP:
        # 短文本直接处理
        print("  [Info] 短文本，直接提取大纲", flush=True)
        outline = _extract_outline_direct(text, llm_service)
        return outline, []
    
    # 长文本分段处理
    print("  [Info] 长文本，启用分段处理...", flush=True)
    
    # 第一步：识别章节边界
    print("  [Step 1] 识别章节边界...", flush=True)
    chapters = _split_into_chapters(text)
    
    if not chapters:
        return _get_default_outline(), []
    
    # 第二步：分组提取摘要
    print("  [Step 2] 分组提取章节摘要...", flush=True)
    groups = _group_chapters(chapters)
    total_groups = len(groups)
    print(f"  [Info] 共 {total_groups} 组，预计耗时 {total_groups * 15} 秒", flush=True)
    
    # 检查断点续传
    start_idx = 0
    summaries = []
    checkpoint = _load_checkpoint()
    if checkpoint and checkpoint.get("summaries"):
        saved_count = len(checkpoint["summaries"])
        if saved_count > 0 and saved_count < total_groups:
            print(f"  [Info] 发现断点，从第 {saved_count + 1} 组继续...", flush=True)
            summaries = checkpoint["summaries"]
            start_idx = saved_count
    
    # 处理每组章节
    for i in range(start_idx, total_groups):
        group = groups[i]
        print(f"  [{i+1}/{total_groups}] 正在提取第 {group['chapters']} 章摘要...", end="", flush=True)
        
        try:
            summary = _extract_chapter_group_summary(group, llm_service)
            summaries.append(summary)
            print(" ✓", flush=True)
            
            # 每处理完一组就保存断点
            _save_checkpoint(summaries, i + 1, total_groups)
            
        except Exception as e:
            print(f" ✗ 失败: {e}", flush=True)
            # 保存当前进度
            _save_checkpoint(summaries, i, total_groups)
            raise
        
        # 避免频率限制
        if i < total_groups - 1:
            time.sleep(LLM_CALL_INTERVAL)
    
    # 第三步：合并生成完整大纲
    print("  [Step 3] 合并生成完整大纲...", flush=True)
    outline = _merge_summaries_to_outline(summaries, llm_service)
    
    # 清除断点文件
    _clear_checkpoint()
    
    return outline, summaries


def _extract_outline_direct(text: str, llm_service: ArkLLMService) -> dict:
    """直接提取大纲（短文本）"""
    prompt = _load_prompt()
    
    user_prompt = f"请从以下小说文本中提取故事大纲：\n\n{text}"
    
    try:
        response = llm_service.generate_text(
            system_prompt=prompt,
            user_prompt=user_prompt,
            temperature=0.3,
        )
        
        # 解析 JSON
        json_str = response.strip()
        if "```json" in json_str:
            start = json_str.find("```json") + 7
            end = json_str.find("```", start)
            json_str = json_str[start:end].strip()
        elif "```" in json_str:
            start = json_str.find("```") + 3
            end = json_str.find("```", start)
            json_str = json_str[start:end].strip()
        
        outline = json.loads(json_str)
        return outline
        
    except json.JSONDecodeError as e:
        print(f"  ⚠️  JSON 解析失败: {e}")
        return _get_default_outline()
    except Exception as e:
        print(f"  ⚠️  LLM 调用失败: {e}")
        return _get_default_outline()


def outline_extractor_node(state: WorkflowState) -> dict:
    """
    LangGraph 节点函数：大纲提取器
    
    输入：novel_text（原始小说文本）
    输出：story_outline（大纲结构）
    """
    print("\n📋 [大纲提取器 Agent] 开始分析小说...", flush=True)
    
    raw_text = state.get("novel_text", "")
    
    if not raw_text:
        print("  ⚠️  没有输入文本，跳过大纲提取", flush=True)
        return {"story_outline": _get_default_outline()}
    
    # 检查 LLM 服务
    if not LLM_AVAILABLE:
        print("  ⚠️  LLM 服务不可用，跳过大纲提取", flush=True)
        return {"story_outline": _get_default_outline()}
    
    llm_service = ArkLLMService()
    if not llm_service.client:
        print("  ⚠️  LLM 客户端未初始化，跳过大纲提取", flush=True)
        return {"story_outline": _get_default_outline()}
    
    # 提取大纲
    outline, summaries = _extract_outline_with_llm(raw_text, llm_service)
    
    # 保存大纲到文件
    _save_outline_to_file(outline, summaries)
    
    # 打印提取结果摘要
    print("\n  ════════════════════════════════════════", flush=True)
    print(f"  📖 故事标题: {outline.get('title', '未知')}", flush=True)
    print(f"  ??️  类型: {outline.get('genre', '未知')}", flush=True)
    
    core_chars = outline.get('core_characters', [])
    print(f"\n  👥 核心角色 ({len(core_chars)} 人):", flush=True)
    for char in core_chars[:5]:
        importance = "★" * char.get('importance', 1)
        print(f"     • {char.get('name')} ({char.get('role')}) {importance}", flush=True)
    
    summary = outline.get('main_plot_summary', '')
    print(f"\n  📝 主线摘要:", flush=True)
    print(f"     {summary[:150]}{'...' if len(summary) > 150 else ''}", flush=True)
    
    key_scenes = outline.get('key_scenes', [])
    print(f"\n  🏞️  关键场景 ({len(key_scenes)} 个):", flush=True)
    print(f"     {', '.join(key_scenes[:5])}{'...' if len(key_scenes) > 5 else ''}", flush=True)
    
    segments = outline.get('chapter_segments', [])
    print(f"\n  📑 剧情分段 ({len(segments)} 段):", flush=True)
    for seg in segments[:3]:
        print(f"     [{seg.get('chapters')}] {seg.get('theme')}", flush=True)
    if len(segments) > 3:
        print(f"     ... 还有 {len(segments) - 3} 段", flush=True)
    
    print("  ════════════════════════════════════════", flush=True)
    
    return {"story_outline": outline}