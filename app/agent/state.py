from typing import Annotated, TypedDict, Optional, Any, List, Dict
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    project_path: str
    base_url: str
    model: str

    interrupt_type: Optional[str]                  # file_plan / system_command / python_script
    pending_plan: Optional[Dict[str, Any]]           # {"tool_call_id": str, "plan": List[Dict]}
    pending_command: Optional[Dict[str, Any]]        # {"tool_call_id": str, ...command}
    pending_script: Optional[Dict[str, Any]]         # {"tool_call_id": str, ...script_meta}
    script_risk_level: Optional[str]

    confirmed: Optional[bool]
    tool_outputs: Annotated[list, lambda x, y: (x or []) + y]
    operation_log: Annotated[list, lambda x, y: (x or []) + y]
