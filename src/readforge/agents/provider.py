"""OpenRouter JSON client shared by all EOC agents."""

import json
import os
import time
from typing import Any

import requests


class LLMProviderError(RuntimeError):
    """OpenRouter could not return a valid structured response."""


class LLMProvider:
    @staticmethod
    def invoke_json(system_prompt: str, request: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(3):
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
                        "response_format": {"type": "json_object"},
                        "max_completion_tokens": 1200,
                        "stream": False,
                    },
                    timeout=(5, 100),
                )
                response.raise_for_status()
                break
            except requests.HTTPError as error:
                if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
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
                if attempt < 2:
                    time.sleep(2**attempt)
                    continue
                raise LLMProviderError("OpenRouter request failed") from error

        try:
            content = response.json()["choices"][0]["message"]["content"]
            result = json.loads(content)
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise LLMProviderError(
                "OpenRouter returned invalid structured JSON"
            ) from error
        if not isinstance(result, dict):
            raise LLMProviderError("OpenRouter response must be a JSON object")
        return result
