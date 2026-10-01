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

class DraftedResponse: 
   classification :str
   start_date : str
   task : str  

# shared states used by nodes
class NotesAgentsState(TypedDict):
    task_content: TaskContent
    #classification notes  
    classification: NotesClassification | None
    # generated content
    drafted_response: DraftedResponse 

  

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
    llm_response  = llm.invoke_llm(classification_prompt, state['task_content'])
    
    #updating data int the state
    response =  DraftedResponse(
        classification =  llm_response['intent'],
        start_date = llm_response['date'],
        task = llm_response['main_task']
    )
   
    return {
        'drafted_response': response 
    } 

    
def create_task(state: EmailAgentState) -> bool : 
  #create task in the main function   
  #read the drafted message from the email agent state 
  task_data = state['drafted_response']
  #call the tool 
  response = write_to_file(task_data)
  True


@tool
def write_to_file(state:NotesAgentsState ) -> bool : 
    with open("notes.txt", "a") as f:
        f.write(state['task_content'] + "\n")
    return True 



workflow = StateGraph(NotesAgentsState)

#adding nodes 
workflow.add_Node("classify_intent",infer_intent)
workflow.add_node("")


#compile with checkpointer for persistence , in case run graph with local server 
memory = MemorySaver()
workflow = workflow.compile(checkpointer=memory)