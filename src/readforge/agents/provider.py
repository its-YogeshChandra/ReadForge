"""OpenRouter JSON client shared by all EOC agents."""

import json
import os
import time
from typing import Any

import requests
from pydantic import BaseModel


class LLMProviderError(RuntimeError):
    """OpenRouter could not return a valid structured response."""


class LLMProvider:
    @staticmethod
    def invoke_json(
        system_prompt: str,
        request: dict[str, Any],
        response_model: type[BaseModel],
    ) -> dict[str, Any]:
        for attempt in range(2):
            try:
                response = requests.post(
                    os.getenv(
                        "OPENROUTER_API_URL",
                        "https://openrouter.ai/api/v1/chat/completions",
                    ),
                    headers={
                        "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": os.getenv(
                            "OPENROUTER_MODEL", "z-ai/glm-5.3-flash"
                        ),
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": json.dumps(request)},
                        ],
                        "provider": {
                            "require_parameters": True,
                            "sort": "price",
                            "max_price": {
                                "prompt": float(
                                    os.getenv("OPENROUTER_MAX_INPUT_PRICE", "0.60")
                                ),
                                "completion": float(
                                    os.getenv("OPENROUTER_MAX_OUTPUT_PRICE", "1.75")
                                ),
                            },
                        },
                        "response_format": {
                            "type": "json_schema",
                            "json_schema": {
                                "name": response_model.__name__.lower(),
                                "strict": True,
                                "schema": response_model.model_json_schema(),
                            },
                        },
                        "plugins": [{"id": "response-healing"}],
                        "max_completion_tokens": 2400,
                        "stream": False,
                    },
                    timeout=(5, 100),
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                return response_model.model_validate_json(content).model_dump(
                    mode="json"
                )
            except requests.HTTPError as error:
                if response.status_code in {429, 500, 502, 503, 504} and attempt < 1:
                    time.sleep(2**attempt)
                    continue
                try:
                    detail = response.json()["error"]["message"]
                except (KeyError, TypeError, ValueError):
                    detail = response.reason
                raise LLMProviderError(
                    f"OpenRouter request failed ({response.status_code}): {detail}"
                ) from error
            except requests.RequestException as error:
                if attempt < 1:
                    time.sleep(2**attempt)
                    continue
                raise LLMProviderError("OpenRouter request failed") from error
            except (KeyError, IndexError, TypeError, ValueError) as error:
                if attempt < 1:
                    time.sleep(2**attempt)
                    continue
                raise LLMProviderError(
                    "OpenRouter returned invalid structured JSON after 2 attempts"
                ) from error

        raise LLMProviderError("OpenRouter request failed")
