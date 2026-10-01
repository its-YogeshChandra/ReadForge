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

#task content 
class TaskContent :
    date: str
    main_task: str
     

class NotesClassification(TypedDict):
    intent: Literal["task", "bugs", "backlog"]


# shared states used by nodes
class NotesAgentsState(TypedDict):
    task_content: TaskContent
    #classification notes  
    classification: NotesClassification | None
    # generated content
    drafted_response: str | None
    messages : list[str] | None


class LLMProvider:

    #goal : infer the user request,
    #return : { "intent" : "task" | "bug" | "backlog" , "main_task" : "task description"}
    #format should be exactly like this 
    def invoke_llm( system_prompt: str, request: TaskContent ) :
        # call the llm to give the classification
        api_url = os.getenv("AGENT_API_URL")
        #convert it according to gemini key 
        try:  
            response = requests.post(api_url, json ={
                "request" : request
            } , headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + os.getenv("api_key")
        } )
             
            return True
        #handle error
        except (ConnectionError) as error:
            print("connection_error : " , error)
            return False
    

         


#classifcation function 
def infer_intent(state: EmailAgentState): 
    """ Use LLM to classify task intent , then route accordingly"""
    #create structured llm that returns email classification dict
    llm = LLMProvider()
    
    #format the task on demand 
    system_prompt = f""" 
    you are a helpful assistant that classifies user requests into tasks , bugs or backlog items 
    Classify the following user request and determine 
    if its a task , bug or backlog item 
    Provide classification including intent and main_task .
    """
    classfication = llm.invoke_llm(classification_prompt, state['task_content'])
    
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
    
    #updating data int the state
    state['classification'] = goto
     

    
def create_task(state: EmailAgentState) -> bool : 
         


@tool
def write_to_file(state:NotesAgentsState ) -> bool : 
    with open("notes.txt", "a") as f:
        f.write(state['task_content'] + "\n")
    return True 



workflow = StateGraph(NotesAgentsState)

workflow.add_Node("classify_intent",infer_intent)
workflow.add_node("")

#compile with checkpointer for persistence , in case run graph with local server 
memory = MemorySaver()
workflow = workflow.compile(checkpointer=memory)