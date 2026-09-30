# langgraph used to create statful agents
# note taking ai agent
from typing import Literal, TypedDict
from langgraph.graph import MessagesState, StateGraph, MessageGraph, START, END
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemoySaver
from langgraph.types import RetryPolicy
from langchain.messages import HumanMessage
import requests

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



class LLMProvider:
    
    def give_llm_structure(state: EmailAgentState):
        #call the llm to give the structure 
        api_url = os.getenv("OPENAI_API_URL") 
        response = requests.post(LLMProvider.api_url, json ={
            """ give me the ouput in the form of json with the following structure 
            """,
            { "type": "NotesClassification"}
        } , headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + os.getenv("OPENAI_API_KEY")
        } )
        
        #if failed to provide structure to the llm
        return {"type": "NotesClassification"}
    
    def call_llm()  : 
        classification = structured_llm.invoke()
    

         
        
#reading and classification node 
#reading function 
def read_task(state: NotesAgentsState) -> dict : 
    """Extract and parse task content"""
    #in production  this would connect to your email service 
    return {
        "messages": [HumanMessage(content = f"Processing email : {state['task_content']}" )]
    }

#classifcation function 
def classify_intent(state: EmailAgentState)-> Command[Literal["task", "bug", "backlog"]] : 
    """ Use LLM to classify task intent , then route accordingly"""
    #create structured llm that returns email classification dict
    structured_llm = give_llm_structure()

    #format the task on demand 
    classification_prompt = f""" Classify the following user request and determine 
    if its a task , bug or backlog item 
    
    user request = {state['task_content']} 
    
    Provide classification including intent, start_date, end_date, and main_task .
    """
    classfication = structured_llm.invoke(prompt="",state ={
        "task_content": state['task_content']
    })
    
    return classfication

    #determine next node based on classification
    if classfication['intent'] == "task" :
        goto = "task" 
    elif classfication['intent'] == "bug" :
        goto = "bug" 
    elif classfication['intent'] == "backlog" :
        goto = "backlog" 
    else :
        raise ValueError("Invalid classification") 

    return Command{
        update ={"classification": classification},
        goto =  goto
    }

@tool
def write_to_file(state:NotesAgentsState ) -> bool : 
    with open("notes.txt", "a") as f:
        f.write(state['task_content'] + "\n")
    return True 



workflow = StateGraph(NotesAgentsState)

workflow.add_Node("read_task",read_task)
workflow.add_Node("classify_intent",classify_intent)

#compile with checkpointer for persistence , in case run graph with local server 
memory = MemorySaver()
workflow = workflow.compile(checkpointer=memory)