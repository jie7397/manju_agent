"""
agents/prompt_utils.py
──────────────────────
安全的 Prompt 模板渲染工具。

问题背景：
  Prompt Markdown 文件中包含大量 JSON 示例（如 {"character": "苏凛", ...}），
  这些花括号会与 Python str.format() 冲突，导致 KeyError。

解决方案：
  用简单的字符串替换代替 str.format()：
  先将 Prompt 中所有 {变量名} 占位符替换为对应值，其余花括号原样保留。
"""


def render_prompt(template: str, **kwargs) -> str:
    """
    安全渲染 Prompt 模板，只替换显式声明的 {变量名} 占位符，
    不触动 JSON 示例中的其他花括号。

    Args:
        template: Prompt 模板字符串
        **kwargs: 要替换的变量名=值

    Returns:
        渲染后的 Prompt 字符串
    """
    result = template
    for key, value in kwargs.items():
        # 精确匹配 {key}，用 str(value) 替换
        result = result.replace("{" + key + "}", str(value))
    return result
