"""
utils/chunker.py
─────────────────
长文本自动分段工具。

真实网文一章动辄 5000-10000 字，直接输入会：
  1. 超出部分模型的上下文长度限制
  2. 导致 LLM 开始"概括"而非精细改编，质量大幅下降

分段策略：
  - 优先在"段落边界"（双换行）处切割，保持段落完整性
  - 章节分隔线（---/***）优先作为切割点
  - 每个 chunk 控制在 CHUNK_SIZE 字符以内
  - 相邻 chunk 之间保留少量"上下文重叠"，帮助 LLM 理解连续性
"""

import re
from config import CHUNK_SIZE, CHUNK_OVERLAP


def split_into_chunks(
    text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP
) -> list[str]:
    """
    将长文本智能分割为多个 chunk。

    Args:
        text: 原始网文文本
        chunk_size: 每个 chunk 的最大字符数（默认 2000）
        overlap: 相邻 chunk 的重叠字符数（保留上下文，默认 200）

    Returns:
        分割后的文本列表；若文本不超过 chunk_size，直接返回 [text]

    分割优先级：
        1. 章节分隔线（--- / *** / ===）
        2. 段落边界（双换行）
        3. 句子结尾（。！？）
        4. 强制按字符数切割（兜底）
    """
    text = text.strip()

    # 短文本直接返回
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    # 先尝试按章节分隔线拆分
    sections = re.split(r"\n[-─*═=]{3,}\n", text)

    if len(sections) > 1:
        # 每个 section 再按 chunk_size 细分
        for section in sections:
            section = section.strip()
            if not section:
                continue
            if len(section) <= chunk_size:
                chunks.append(section)
            else:
                chunks.extend(_split_by_paragraphs(section, chunk_size))
    else:
        chunks = _split_by_paragraphs(text, chunk_size)

    # 添加 overlap：在每个 chunk 末尾加上下一个 chunk 的前 overlap 字符
    if overlap > 0 and len(chunks) > 1:
        overlapped = []
        for i, chunk in enumerate(chunks):
            if i < len(chunks) - 1:
                # 从下一个 chunk 取前 overlap 个字符
                next_preview = chunks[i + 1][:overlap]
                chunk_with_context = (
                    chunk + "\n\n【→ 接续段落预览】" + next_preview + "..."
                )
                overlapped.append(chunk_with_context)
            else:
                overlapped.append(chunk)
        return overlapped

    return chunks


def _split_by_paragraphs(text: str, chunk_size: int) -> list[str]:
    """按段落边界分割，段落不可分割"""
    paragraphs = re.split(r"\n\n+", text)
    chunks = []
    current_parts = []
    current_len = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        para_len = len(para)

        # 如果单个段落本身就超过 chunk_size，按句子再拆
        if para_len > chunk_size:
            if current_parts:
                chunks.append("\n\n".join(current_parts))
                current_parts = []
                current_len = 0
            chunks.extend(_split_by_sentences(para, chunk_size))
            continue

        if current_len + para_len + 2 > chunk_size and current_parts:
            chunks.append("\n\n".join(current_parts))
            current_parts = [para]
            current_len = para_len
        else:
            current_parts.append(para)
            current_len += para_len + 2  # +2 for \n\n

    if current_parts:
        chunks.append("\n\n".join(current_parts))

    return chunks


def _split_by_sentences(text: str, chunk_size: int) -> list[str]:
    """按句子结尾拆分（兜底方案）"""
    sentences = re.split(r"(?<=[。！？…])", text)
    chunks = []
    current = ""

    for sentence in sentences:
        if len(current) + len(sentence) > chunk_size and current:
            chunks.append(current.strip())
            current = sentence
        else:
            current += sentence

    if current.strip():
        chunks.append(current.strip())

    # 如果还是有超长的，强制按字符切
    final = []
    for chunk in chunks:
        if len(chunk) > chunk_size:
            for i in range(0, len(chunk), chunk_size):
                final.append(chunk[i : i + chunk_size])
        else:
            final.append(chunk)

    return final


def get_chunk_info(text: str, chunk_size: int = CHUNK_SIZE) -> dict:
    """
    预分析文本，返回分段信息（不实际分段，供用户决策）

    Returns:
        {"total_chars": int, "estimated_chunks": int, "needs_chunking": bool}
    """
    total = len(text)
    estimated = max(1, (total + chunk_size - 1) // chunk_size)
    return {
        "total_chars": total,
        "estimated_chunks": estimated,
        "needs_chunking": total > chunk_size,
    }
