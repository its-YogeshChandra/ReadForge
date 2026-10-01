# langgraph used to create statful agents
# note taking ai agent
import json
import os
from typing import Literal, NotRequired, TypedDict

import requests
from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph

load_dotenv()

#task content
class TaskContent(TypedDict):
    date: str
    main_task: str
     

class NotesClassification(TypedDict):
    intent: Literal["task", "bug", "backlog"]

class DraftedResponse(TypedDict):
    classification: Literal["task", "bug", "backlog"]
    start_date: str
    task: str

# shared states used by nodes
class NotesAgentsState(TypedDict):
    task_content: TaskContent
    classification: NotRequired[NotesClassification]
    drafted_response: NotRequired[DraftedResponse]

class LLMProvider:

    #goal : infer the user request,
    #return : { "intent" : "task" | "bug" | "backlog" }
    #format should be exactly like this 
    @staticmethod
    def invoke_llm(system_prompt: str, request: TaskContent) -> NotesClassification:
        response = requests.post(
            os.environ["AGENT_API_URL"],
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": os.environ["GEMINI_API_KEY"],
            },
            json={
                "system_instruction": {"parts": [{"text": system_prompt}]},
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": json.dumps(request)}],
                    }
                ],
                "generationConfig": {
                    "response_mime_type": "application/json",
                    "response_schema": {
                        "type": "object",
                        "properties": {
                            "intent": {
                                "type": "string",
                                "enum": ["task", "bug", "backlog"],
                            },
                        },
                        "required": ["intent"],
                    },
                },
            },
            timeout=30,
        )
        response.raise_for_status()

        try:
            result = json.loads(
                response.json()["candidates"][0]["content"]["parts"][0]["text"]
            )
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise ValueError("Gemini returned an invalid structured response") from error

        if (
            not isinstance(result, dict)
            or result.get("intent") not in {"task", "bug", "backlog"}
        ):
            raise ValueError("Gemini returned an invalid note classification")
        return result
    


#classifcation function 
def infer_intent(state: NotesAgentsState): 
    """ Use LLM to classify task intent , then route accordingly"""
    system_prompt = """
    You classify user requests as task, bug, or backlog.
    Return the intent that best matches the supplied task data.
    """
    return {
        "classification": LLMProvider.invoke_llm(system_prompt, state["task_content"])
    }

def create_task(state: NotesAgentsState) -> dict[str, DraftedResponse]:
    task_content = state["task_content"]
    response: DraftedResponse = {
        "classification": state["classification"]["intent"],
        "start_date": task_content["date"],
        "task": task_content["main_task"],
    }
    with open("notes.txt", "a", encoding="utf-8") as file:
        file.write(json.dumps(response) + "\n")
    return {"drafted_response": response}



workflow_builder = StateGraph(NotesAgentsState)

#adding nodes 
workflow_builder.add_node("infer_intent", infer_intent)
workflow_builder.add_node("create_task", create_task)
workflow_builder.add_edge(START, "infer_intent")
workflow_builder.add_edge("infer_intent", "create_task")
workflow_builder.add_edge("create_task", END)

workflow = workflow_builder.compile()


def main() -> None:
    task_content: TaskContent = {
        "date": input("Date: ").strip(),
        "main_task": input("Task: ").strip(),
    }
    if not task_content["date"] or not task_content["main_task"]:
        raise ValueError("Date and task are required")

    result = workflow.invoke({"task_content": task_content})
    print(json.dumps(result["drafted_response"], indent=2))


if __name__ == "__main__":
    main()
