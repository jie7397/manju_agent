"""
state.py (更新版)
────────────────────
定义 LangGraph 的全局共享状态。

新增字段（v2）：
  - character_sheet      : 角色提取 Agent 输出的角色档案
  - skip_human_review    : 是否跳过人工审核节点（打回修改后不再复审）
  - human_review_target  : 人工审核后的路由目标
"""

from typing import TypedDict, Optional, Literal


# ── 大纲提取器数据结构 ──────────────────────────────────────────────────────

class CoreCharacter(TypedDict):
    """大纲中的核心角色（简化版）"""
    name: str
    role: str  # 主角/反派/配角/导师等
    importance: int  # 1-5，5为最高
    brief_description: str


class ChapterSegment(TypedDict):
    """章节分段"""
    segment_id: int
    chapters: str  # 如 "1-3"
    theme: str
    core_characters: list[str]
    summary: str


class StoryOutline(TypedDict):
    """大纲提取器输出的故事大纲"""
    title: str
    genre: str
    core_characters: list[CoreCharacter]
    main_plot_summary: str
    key_scenes: list[str]
    chapter_segments: list[ChapterSegment]


# ── 角色数据结构 ────────────────────────────────────────────────────────────

class CharacterProfile(TypedDict):
    """单个角色档案"""

    name: str  # 中文名
    name_en: str  # 英文拼音（用于 AI 绘画 Prompt）
    role: str  # protagonist / antagonist / supporting
    appearance: str  # 外貌描述（中文，供编剧参考）
    personality: str  # 性格特点
    visual_signature: str  # 标志性视觉元素（如：发光的蓝色剑）
    image_keywords: str  # 英文绘画关键词（直接注入 Prompt，保证一致性）


class CharacterSheet(TypedDict):
    """角色档案库，由角色提取 Agent 生成"""

    main_characters: list[CharacterProfile]
    world_visual_style: str  # 世界观整体视觉风格描述
    color_palette: str  # 主色调（英文关键词，直接用于 Prompt）


class ScreenplayScene(TypedDict):
    """编剧输出的单个场景结构"""

    scene_number: int
    setting: str
    action: str
    dialogue: list[
        dict
    ]  # [{"character": "...", "line": "...", "type": "VO/OS/DIALOGUE"}]
    visual_hint: str


class StoryboardScene(TypedDict):
    """分镜师输出的单个场景结构"""

    scene_number: int
    shot_type: str
    image_prompt: str
    camera_movement: str
    visual_notes: str
    active_character_names: list  # 当前镜头中出现的主要角色名称列表（用于角色一致性追踪）


class SoundScene(TypedDict):
    """音效师输出的单个场景结构"""

    scene_number: int
    ambience: str
    foley: str
    bgm_mood: str


class DirectorFeedback(TypedDict):
    """导演的单条审核反馈"""

    target_agent: str
    scene_number: int
    issue: str
    instruction: str


class WorkflowState(TypedDict):
    """
    整个多智能体工作流的全局状态

    数据流向（v4 - 大纲驱动）：
      Input → outline_extractor → character_extractor → screenwriter → production_designer → storyboard → ...
                    │
                    ↓
            story_outline (核心角色、主线摘要、分段规划)
                    │
                    ↓ (后续 agent 基于大纲工作)
    """

    # ── 输入 ──────────────────────────────────────────────
    novel_text: str
    novel_type: str

    # ── 大纲提取器输出（v4 新增）─────────────────────────
    story_outline: Optional[StoryOutline]

    # ── 角色档案（新） ─────────────────────────────────────
    character_sheet: Optional[CharacterSheet]

    # ── 图片生成产出（v3 新增）────────────────────────────
    character_images: dict  # {character_id: {"anchor_sheet": path, "prompt": str}}
    scene_images: dict  # {location_id: {"scene_anchor": path, "prompt": str}}
    image_prompts: dict  # 存储所有图片的 prompt，供审核使用

    # ── 编剧输出 ──────────────────────────────────────────
    screenplay_scenes: list[ScreenplayScene]

    # ── 分镜师输出 ────────────────────────────────────────
    storyboard_scenes: list[StoryboardScene]

    # ── 音效师输出 ────────────────────────────────────────
    sound_scenes: list[SoundScene]

    # ── 导演审核 ──────────────────────────────────────────
    director_feedback: list[DirectorFeedback]
    revision_target: Optional[
        Literal["screenwriter", "storyboard", "sound_designer", "character_extractor", "production_designer", "approved"]
    ]
    revision_count: int

    # ── 人工审核控制（新） ─────────────────────────────────
    skip_human_review: bool  # 首次人工审核后设为 True，避免反复弹出
    human_review_target: str  # 人工审核决定的下一步：director / 各 Agent

    # ── 最终产出 ──────────────────────────────────────────
    is_approved: bool
    final_script: Optional[str]
