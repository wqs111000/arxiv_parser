"""
Prompts 管理模块
统一管理所有 AI 提示词
"""

# System Prompts
SYSTEM_PROMPT_SUMMARY = """You are a professional paper analyst. You should avoid unnecessarily long replies and instead provide concise, detailed, and precise answers using correct terminology."""

SYSTEM_PROMPT_FULL_ANALYSIS = """You are a professional academic paper analyst. Always respond in Chinese."""


# User Prompts
def get_summary_prompt(text: str) -> str:
    """
    生成论文摘要总结的 prompt
    
    Args:
        text: 论文摘要内容
    
    Returns:
        格式化后的 prompt 字符串
    """
    return f"""请对下面的学术论文进行结构化总结，总字数 300–500 字，语言简洁专业。
严格按下面 5 个标题输出，每个标题一段，不要列表、不要符号、不要多余解释。
TL;DR：
【一句话概括论文核心贡献】
动机：
【说明要解决的问题、现有方法不足、研究意义】
方法：
【简述模型、算法、实验设计、技术方案】
结果：
【关键指标、对比效果、实验结论】
总结：
【论文价值、局限、未来方向】
论文内容：
{text}
"""


# 全文分析 Prompt
FULL_ANALYSIS_PROMPT = """请对该学术论文进行深度全文剖析，输出格式严格遵循Markdown，需完整包含以下章节，要求内容详尽专业、语言简洁准确、逻辑连贯，**禁止出现任何公式、图片及无关冗余信息**：

### 核心贡献
明确阐述论文的核心研究成果、理论/应用价值，重点说明是否开源相关资源（代码、模型、数据集等），若开源需简要提及开源平台或获取方式。

### 研究背景与动机
结合该领域研究现状、现有研究存在的痛点/空白，清晰简洁地说明本文的研究初衷、研究意义，以及要解决的核心问题，避免泛泛而谈。

### 技术方法详解
分层次、有条理地拆解论文采用的核心技术、研究方法、实验设计思路，明确各方法的核心逻辑、实施步骤及适用场景，重点突出方法的核心原理，无需冗余铺垫。

### 创新点与局限性
1.  创新点：精准提炼本文区别于现有研究的核心创新（理论创新、方法创新、应用创新等），每条创新点简要说明其独特性及优势；
2.  局限性：客观分析论文存在的不足（研究范围、方法缺陷、实验局限性等），不回避短板，表述客观中立。

### 总结与展望
1.  总结：简要概括论文的核心研究结论、主要成果，以及成果的理论/实践价值；
2.  展望：结合本文局限性及领域发展趋势，合理提出未来可进一步研究的方向、改进思路，具有可行性和针对性"""
