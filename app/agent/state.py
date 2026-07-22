from typing import Annotated, TypedDict, Optional, Any, List, Dict, NotRequired
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    project_path: str
    project_id: str
    base_url: str
    model: str
    # Legacy checkpoints may contain this field. New threads keep secrets only
    # in process memory via RunnableConfig so the key is not checkpointed.
    api_key: NotRequired[Optional[str]]

    interrupt_type: Optional[str]                  # file_plan / system_command / python_script
    pending_plan: Optional[Dict[str, Any]]           # {"tool_call_id": str, "plan": List[Dict]}
    pending_command: Optional[Dict[str, Any]]        # {"tool_call_id": str, ...command}
    pending_script: Optional[Dict[str, Any]]         # {"tool_call_id": str, ...script_meta}
    script_risk_level: Optional[str]
    pending_radiomics_plan: Optional[Dict[str, Any]] # {"tool_call_id": str, ...radiomics_plan}
    pending_radiomics_execution: Optional[Dict[str, Any]]  # {"tool_call_id": str, ...radiomics_execution}
    pending_radiomics_analysis: Optional[Dict[str, Any]]    # {"tool_call_id": str, ...analysis meta}
    pending_subagent: Optional[Dict[str, Any]]              # {"tool_call_id": str, "task": str}
    pending_feature_statistics: Optional[Dict[str, Any]]    # {"tool_call_id": str, ...stats meta}
    pending_choice: Optional[Dict[str, Any]]                # {"tool_call_id": str, "question": str, "options": [...]}
    choice_answer: Optional[str]                            # 用户在选择面板中提交的答案

    context_usage: Optional[Dict[str, Any]]      # 最近一次 LLM 调用的 token 用量
    todos: NotRequired[List[Dict[str, str]]]     # 计划面板步骤列表，由 update_todo_list 工具全量替换
    confirmed: Optional[bool]
    other_instruction: Optional[str]             # 审批 "other" 动作时用户给出的替代指令
    tool_outputs: Annotated[list, lambda x, y: (x or []) + y]
    operation_log: Annotated[list, lambda x, y: (x or []) + y]
