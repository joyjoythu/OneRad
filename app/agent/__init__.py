from app.agent.state import AgentState
from app.constants import DEEPSEEK_MODEL


def create_agent_graph(checkpointer=None):
    """Lazily import and build the compiled LangGraph agent."""
    from app.agent.graph import create_agent_graph as _create_agent_graph
    return _create_agent_graph(checkpointer=checkpointer)


def build_initial_state(project: dict) -> AgentState:
    return {
        "messages": [],
        "project_path": project["path"],
        "project_id": project["id"],
        "base_url": "https://api.deepseek.com/v1",
        "model": DEEPSEEK_MODEL,
        "interrupt_type": None,
        "pending_plan": None,
        "pending_command": None,
        "pending_script": None,
        "pending_radiomics_analysis": None,
        "script_risk_level": None,
        "confirmed": None,
        "tool_outputs": [],
        "operation_log": [],
    }
