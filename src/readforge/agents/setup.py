# langgraph used to create statful agents
# note taking ai agent
from typing import Literal, TypedDict
from langgraph.graph import MessagesState, StateGraph, MessageGraph, START, END
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemoySaver
from langgraph.types import RetryPolicy
from langchain.messages import HumanMessage

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
    messages : list[str] | None

def give_llm_structure():
#call the llm to give the structure 
    return {"type": "NotesClassification"}

def read_task(state: NotesAgentsState) -> dict : 
    """Extract and parse task content"""
    #in production  this would connect to your email service 
    return {
        "messages": [HumanMessage(content = f"Processing email : {state['task_content']}" )]
    }

def classify_intent(state: EmailAgentState)-> Command[Literal["task", "bug", "backlog"]] : 
    """ Use LLM to classify task intent , then route accordingly"""
    #create structured llm that returns email classification dict
    structured_llm = give_llm_structure() 
    
    
    task = state["task_content"]
  
    # in production use OpenAI
    response = mock_llm(task)
    return { "classification" : response}  # type: ignore 


workflow = StateGraph(NotesAgentsState)



@tool
def router(state: NotesAgentsState) -> str:
    return "get_square_root"
    

@tool
def get_square_root(num: float) -> float:
    return num * num

@tool
def get_llm_square() -> float: 
    return 