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

    数据流向（v2）：
      Input → character_extractor → screenwriter → storyboard → sound_designer
                                                                     │
                                              [HUMAN_REVIEW=true时] ↓
                                                              human_reviewer
                                                                     │
                                                              ↓─────────────────────────┐
                                                           director                     │
                                                       ↙         ↘                     │
                                                     END    打回给各 Agent ←────────────┘
    """

    # ── 输入 ──────────────────────────────────────────────
    novel_text: str
    novel_type: str

    # ── 角色档案（新） ─────────────────────────────────────
    character_sheet: Optional[CharacterSheet]

    # ── 编剧输出 ──────────────────────────────────────────
    screenplay_scenes: list[ScreenplayScene]

    # ── 分镜师输出 ────────────────────────────────────────
    storyboard_scenes: list[StoryboardScene]

    # ── 音效师输出 ────────────────────────────────────────
    sound_scenes: list[SoundScene]

    # ── 导演审核 ──────────────────────────────────────────
    director_feedback: list[DirectorFeedback]
    revision_target: Optional[
        Literal["screenwriter", "storyboard", "sound_designer", "approved"]
    ]
    revision_count: int

    # ── 人工审核控制（新） ─────────────────────────────────
    skip_human_review: bool  # 首次人工审核后设为 True，避免反复弹出
    human_review_target: str  # 人工审核决定的下一步：director / 各 Agent

    # ── 最终产出 ──────────────────────────────────────────
    is_approved: bool
    final_script: Optional[str]
