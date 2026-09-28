# extend the function to create embeddings out of the ocr

# model used clip4 all api : self hosted


class EmbeddingsPayload:
    file_id: str | None
    file_name: str
    text_data: str


def text_embeddings(data: EmbeddingsPayload):
    # take the text from the
    return None
