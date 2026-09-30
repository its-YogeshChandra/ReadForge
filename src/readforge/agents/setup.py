# langgraph used to create statful agents
# note taking ai agent
from typing import Literal, TypedDict

from langgraph.graph import MessagesState, StateGraph, MessageGraph, START, END
from langchain_core.tools import tool


def mock_llm(state: MessagesState):
    return {}


class NotesClassification(TypedDict):
    intent: Literal["task", "bugs", "backlog"]


# shared states used by nodes
class NotesAgentsState(TypedDict):
    task_content: str
    start_date: str
    end_data: str

    # classifying result
    classification: NotesClassification | None

    # raw search | api result
    user_query: list[str]

    # generated content
    drafted_response: str | None


# macro for defining the fuction that can actually called by agent
@tool
def get_sum(first: int, second: int) -> int:
    return first * second
