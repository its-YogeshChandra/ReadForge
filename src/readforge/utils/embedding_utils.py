"""Client for the self-hosted text embedding service."""

from dataclasses import dataclass
from math import isfinite
import os

from dotenv import load_dotenv
import requests

load_dotenv()


# need to add retry true or false value
class EmbeddingServiceError(RuntimeError):
    """The embedding service could not return a usable vector."""


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


def embed_text(data: EmbeddingsPayload) -> list[float]:
    """Return one embedding vector for ``data.text_data``."""
    if not isinstance(data, EmbeddingsPayload):
        raise TypeError("data must be an EmbeddingsPayload")

    api_url = os.getenv("CLIP_API_URL", "")
    if not api_url:
        raise EmbeddingServiceError("CLIP_API_URL is not set")

    try:
        response = requests.post(
            f"{api_url}embedding/text",
            json={"texts": [data.text_data]},
            timeout=(5, 120),
        )
        response.raise_for_status()
        body = response.json()
    except requests.exceptions.JSONDecodeError as error:
        raise EmbeddingServiceError(
            "Embedding service returned invalid JSON"
        ) from error
    except requests.RequestException as error:
        raise EmbeddingServiceError("Embedding request failed") from error

    if (
        not isinstance(body, list)
        or len(body) != 1
        or not isinstance(body[0], dict)
        or not isinstance(body[0].get("vector"), list)
        or not body[0]["vector"]
    ):
        raise EmbeddingServiceError("Embedding service returned an invalid response")

    vector = body[0]["vector"]
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
        for value in vector
    ):
        raise EmbeddingServiceError("Embedding vector contains an invalid value")

    return [float(value) for value in vector]
