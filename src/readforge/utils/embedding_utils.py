"""OpenRouter text embedding client."""

from dataclasses import dataclass
from math import isfinite
import os
import time

import requests

OPENROUTER_EMBEDDINGS_URL = "https://openrouter.ai/api/v1/embeddings"


class EmbeddingServiceError(RuntimeError):
    """OpenRouter could not return a usable embedding vector."""


@dataclass(frozen=True, slots=True)
class EmbeddingsPayload:
    file_name: str
    text_data: str

    def __post_init__(self) -> None:
        if not isinstance(self.file_name, str):
            raise TypeError("file_name must be a string")
        if not isinstance(self.text_data, str):
            raise TypeError("text_data must be a string")
        if not self.file_name.strip():
            raise ValueError("file_name must not be empty")
        if not self.text_data.strip():
            raise ValueError("text_data must not be empty")


def embedding_model() -> str:
    """Return the configured OpenRouter embedding model."""
    model = os.getenv("OPENROUTER_EMBEDDING_MODEL", "").strip()
    if not model:
        raise EmbeddingServiceError("OPENROUTER_EMBEDDING_MODEL is not set")
    return model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Return one OpenRouter embedding for each input string."""
    if not texts or any(not isinstance(text, str) or not text.strip() for text in texts):
        raise ValueError("texts must contain non-empty strings")

    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        raise EmbeddingServiceError("OPENROUTER_API_KEY is not set")

    for attempt in range(3):
        try:
            response = requests.post(
                OPENROUTER_EMBEDDINGS_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": embedding_model(), "input": texts},
                timeout=(5, 120),
            )
            response.raise_for_status()
            body = response.json()
            break
        except requests.exceptions.JSONDecodeError as error:
            raise EmbeddingServiceError(
                "OpenRouter returned invalid embedding JSON"
            ) from error
        except requests.RequestException as error:
            status_code = getattr(error.response, "status_code", None)
            retryable = status_code is None or status_code in {
                429,
                500,
                502,
                503,
                504,
                524,
                529,
            }
            if retryable and attempt < 2:
                time.sleep(2**attempt)
                continue
            try:
                detail = error.response.json()["error"]["message"]
            except (AttributeError, KeyError, TypeError, ValueError):
                detail = "Embedding request failed"
            raise EmbeddingServiceError(
                f"OpenRouter embedding request failed ({status_code}): {detail}"
            ) from error

    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list) or len(data) != len(texts):
        raise EmbeddingServiceError("OpenRouter returned an invalid embedding response")

    if any(not isinstance(item, dict) for item in data):
        raise EmbeddingServiceError("OpenRouter returned an invalid embedding response")
    ordered = sorted(data, key=lambda item: item.get("index", -1))
    vectors: list[list[float]] = []
    for index, item in enumerate(ordered):
        vector = item.get("embedding") if isinstance(item, dict) else None
        if (
            not isinstance(item, dict)
            or item.get("index") != index
            or not isinstance(vector, list)
            or not vector
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
                for value in vector
            )
        ):
            raise EmbeddingServiceError(
                "OpenRouter returned an invalid embedding response"
            )
        vectors.append([float(value) for value in vector])
    if len({len(vector) for vector in vectors}) != 1:
        raise EmbeddingServiceError("OpenRouter returned inconsistent vector sizes")
    return vectors


def embed_text(data: EmbeddingsPayload) -> list[float]:
    """Return one embedding vector for ``data.text_data``."""
    if not isinstance(data, EmbeddingsPayload):
        raise TypeError("data must be an EmbeddingsPayload")
    return embed_texts([data.text_data])[0]
