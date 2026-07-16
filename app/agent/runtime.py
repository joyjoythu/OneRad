"""智能体线程的运行时上下文注册表。

图节点是普通的同步函数，无法直接访问 FastAPI 的 ``app.state``。本模块以
thread_id 为键保存每个运行中线程的上下文（取消事件、事件循环、SSE 桥），
使节点内部执行的耗时任务（如影像组学特征提取）可以：

- 通过 ``cancel_event`` 响应 /stop 的协作式取消；
- 通过 ``bridge`` + ``loop`` 向 SSE 订阅者推送实时进度。
"""

import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class AgentRunContext:
    """单次流式运行的上下文。cancel_event 由 /stop 置位，由耗时任务轮询。"""

    cancel_event: threading.Event
    loop: Any = None
    bridge: Any = None


_lock = threading.Lock()
_contexts: Dict[str, AgentRunContext] = {}


def register(thread_id: str, loop: Any = None, bridge: Any = None) -> AgentRunContext:
    """为线程登记一个全新的运行时上下文（每次运行使用独立的取消事件）。"""
    ctx = AgentRunContext(cancel_event=threading.Event(), loop=loop, bridge=bridge)
    with _lock:
        _contexts[thread_id] = ctx
    return ctx


def get(thread_id: Optional[str]) -> Optional[AgentRunContext]:
    if not thread_id:
        return None
    with _lock:
        return _contexts.get(thread_id)


def unregister(thread_id: Optional[str]) -> None:
    if not thread_id:
        return
    with _lock:
        _contexts.pop(thread_id, None)


def request_cancel(thread_id: Optional[str]) -> bool:
    """置位线程的取消事件。线程没有运行中的上下文时返回 False。"""
    ctx = get(thread_id)
    if ctx is None:
        return False
    ctx.cancel_event.set()
    return True
