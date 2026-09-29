# extend the function to create embeddings out of the ocr
import os
import requests

# model used clip4 all api : self hosted
CLIP_API_URL = os.getenv("CLIP_API_URL")


# request for the text embedding function
class EmbeddingsPayload:
    file_name: str
    text_data: str


# take the text data from the file name
# call the cli4 text embedding endpoint
# if failed to generate embedding return error
# else return the text embeddings with the file name they belongs too
def embed_text(data: EmbeddingsPayload) -> list[float] | None:

    try:
        response = requests.post(
            f"{CLIP_API_URL}/embedding/text",
            json={"texts": [data.text_data]},
            timeout=120,
        )
        response.raise_for_status()
        vector = response.json()[0]["vector"]
        return vector

    except (ValueError, TypeError) as e:
        if isinstance(e, ValueError):
            print(f"invalid text data: {e}")
            return None

        if isinstance(e, TypeError):
            print(f"invalid text data: {e}")
            return None
