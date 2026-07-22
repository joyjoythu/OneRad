"""项目级跨线程长期记忆：提取与注入。

- ``extract_memories``：用 LLM 从一轮对话中抽取可复用的关键事实。
- ``build_memory_prompt``：从 ProjectStore 读取记忆，拼接为 system prompt 片段。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from app.llm import LLMClient

logger = logging.getLogger(__name__)

# 最多同时注入的记忆条数
MAX_MEMORIES = 20

# 记忆类别 → 中文标题
_CATEGORY_LABELS: Dict[str, str] = {
    "clinical":    "临床信息",
    "decision":    "过往决策",
    "finding":     "分析发现",
    "preference":  "用户偏好",
    "general":     "其他",
}

_EXTRACTION_SYSTEM = (
    "你是信息提取助手。从以下对话中提取可以跨会话复用的长期关键事实。"
    "只提取客观的、结论性的信息——忽略临时性问答、调试过程、问候等无关内容。"
    "每条事实用一句话表达，清晰独立。"
    "返回一个 JSON 数组，每个元素包含：\n"
    '  - category: "clinical" | "decision" | "finding" | "preference" | "general"\n'
    '  - fact: 一句话事实\n'
    "只返回 JSON 数组，不要输出其他内容。没有可提取的事实时返回空数组 []。"
)


def extract_memories(
    messages: List[Dict[str, Any]],
    llm_client: LLMClient,
) -> List[Dict[str, str]]:
    """从消息历史中提取长期记忆事实。

    Args:
        messages: ``_render_messages`` 产出的消息 dict 列表（role/content）。
        llm_client: 具备 ``call_json`` 方法的 LLM 客户端。

    Returns:
        ``[{category, fact}, ...]`` 列表；提取失败或无事可提时返回 []。
    """
    # 只取 user 和 assistant 消息，过滤 system / tool
    dialogue = []
    for m in messages:
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        content = m.get("content") or ""
        # 工具结果太长：截断
        if role == "assistant" and len(content) > 2000:
            content = content[:2000] + "..."
        if len(content) > 1000:
            content = content[:1000] + "..."
        dialogue.append(f"[{role}] {content}")

    if not dialogue:
        return []

    user_prompt = "对话记录：\n" + "\n".join(dialogue[-100:])  # 只取最后 100 条消息行

    try:
        result = llm_client.call_json(
            _EXTRACTION_SYSTEM, user_prompt, temperature=0.1, max_tokens=2000
        )
    except Exception:
        logger.warning("记忆提取 LLM 调用失败", exc_info=True)
        return []

    if not isinstance(result, list):
        logger.debug("记忆提取返回非数组: %s", type(result).__name__)
        return []

    memories: List[Dict[str, str]] = []
    for item in result:
        if not isinstance(item, dict):
            continue
        cat = (item.get("category") or "general").strip()
        fact = (item.get("fact") or "").strip()
        if fact and cat in _CATEGORY_LABELS:
            memories.append({"category": cat, "fact": fact})

    return memories


def build_memory_prompt(
    project_id: str,
    store: Any,  # ProjectStore（避免循环导入）
) -> str:
    """构建注入到 system prompt 中的项目记忆片段。

    Args:
        project_id: 项目 ID。
        store: ``ProjectStore`` 实例。

    Returns:
        Markdown 格式的记忆文本块；无记忆时返回空字符串。
    """
    try:
        rows = store.get_memories(project_id, limit=MAX_MEMORIES)
    except Exception:
        logger.warning("读取项目记忆失败 project_id=%s", project_id, exc_info=True)
        return ""

    if not rows:
        return ""

    # 按类别分组
    buckets: Dict[str, List[str]] = {}
    for row in rows:
        cat = row.get("category", "general")
        fact = row.get("fact", "").strip()
        if not fact:
            continue
        buckets.setdefault(cat, []).append(fact)

    if not buckets:
        return ""

    # 按 _CATEGORY_LABELS 的顺序输出（保证 inject 时的顺序一致）
    lines = ["## 项目记忆（跨会话共享的已知事实）", ""]
    for cat, label in _CATEGORY_LABELS.items():
        facts = buckets.get(cat)
        if not facts:
            continue
        lines.append(f"### {label}")
        for f in facts:
            lines.append(f"- {f}")
        lines.append("")
    lines.append("---")
    return "\n".join(lines)
