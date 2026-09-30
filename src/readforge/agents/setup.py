# langgraph used to create statful agents
# note taking ai agent 
from langgraph.graph import MessagesState, StateGraph, MessageGraph, START, END
from langchain_core.tools import tool


def mock_llm(state: MessagesState):
    return {}

class 


# macro for defining the fuction that can actually called by agent
@tool
def get_sum(first: int, second: int) -> int:
    return first * second
