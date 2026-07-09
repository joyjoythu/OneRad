from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import MemorySaver
from app.agent.state import AgentState
from app.agent.nodes import (
    call_llm,
    process_tool_calls,
    human_review,
    execute_confirmed,
    should_continue,
    route_after_process,
)


def create_agent_graph():
    builder = StateGraph(AgentState)
    builder.add_node("call_llm", call_llm)
    builder.add_node("process_tool_calls", process_tool_calls)
    builder.add_node("human_review", human_review)
    builder.add_node("execute_confirmed", execute_confirmed)

    builder.add_edge(START, "call_llm")
    builder.add_conditional_edges("call_llm", should_continue, {"process_tool_calls": "process_tool_calls", "__end__": END})
    builder.add_conditional_edges("process_tool_calls", route_after_process, {"human_review": "human_review", "call_llm": "call_llm"})
    builder.add_edge("human_review", "execute_confirmed")
    builder.add_edge("execute_confirmed", "call_llm")

    return builder.compile(checkpointer=MemorySaver())
