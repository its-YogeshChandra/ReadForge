# langgraph used to create statful agents
# note taking ai agent
import json
import os
from typing import Literal, NotRequired, TypedDict

import requests
from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph

load_dotenv()


# task content
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
    # goal : infer the user request,
    # return : { "intent" : "task" | "bug" | "backlog" }
    # format should be exactly like this
    @staticmethod
    def invoke_llm(system_prompt: str, request: TaskContent) -> NotesClassification:
        response = requests.post(
            os.getenv(
                "NVIDIA_NIM_API_URL",
                "https://integrate.api.nvidia.com/v1/chat/completions",
            ),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {os.environ['NVIDIA_API_KEY']}",
            },
            json={
                "model": os.environ["NVIDIA_NIM_MODEL"],
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(request)},
                ],
                "temperature": 0.2,
                "max_tokens": 40,
                "chat_template_kwargs": {"enable_thinking": False},
                "stream": False,
            },
            timeout=100,
        )
        response.raise_for_status()

        try:
            intent = response.json()["choices"][0]["message"]["content"].strip().lower()
        except (KeyError, IndexError, TypeError, AttributeError) as error:
            raise ValueError("NVIDIA NIM returned an invalid response") from error

        if intent not in {"task", "bug", "backlog"}:
            raise ValueError(f"NVIDIA NIM returned an invalid note intent: {intent!r}")
        return {"intent": intent}


# classifcation function
def infer_intent(state: NotesAgentsState):
    """Use LLM to classify task intent , then route accordingly"""
    system_prompt = """
    You classify user requests as task, bug, or backlog.
    Return exactly one word: task, bug, or backlog. Do not add punctuation or explanation.
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

# adding nodes
workflow_builder.add_node("infer_intent", infer_intent)
workflow_builder.add_node("create_task", create_task)

#adding edges 
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
