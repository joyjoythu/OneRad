from app.agent.graph import create_agent_graph


def build_initial_state(project: dict) -> dict:
    analysis = project.get("analysis", {})
    return {
        "messages": [],
        "project_path": project["path"],
        "api_key": analysis.get("api_key", ""),
        "base_url": "https://api.deepseek.com/v1",
        "model": analysis.get("model", "deepseek-chat"),
        "interrupt_type": None,
        "pending_plan": None,
        "pending_command": None,
        "pending_script": None,
        "script_risk_level": None,
        "confirmed": None,
        "tool_outputs": [],
        "operation_log": [],
    }
