"""Focused checks for the OpenRouter embedding client."""

from readforge.utils.embedding_utils import EmbeddingsPayload, embed_text
from readforge.utils.reading_util import OcrResponse
from readforge.worker import _embed_pages


class _Response:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return {
            "data": [{"index": 0, "embedding": [0.25, -0.5]}],
            "model": "openai/text-embedding-3-small",
        }


def test_embed_text_uses_openrouter_contract(monkeypatch) -> None:
    request = {}

    def post(url, **kwargs):
        request.update(url=url, **kwargs)
        return _Response()

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv(
        "OPENROUTER_EMBEDDING_MODEL", "openai/text-embedding-3-small"
    )
    monkeypatch.setattr("readforge.utils.embedding_utils.requests.post", post)

    assert embed_text(EmbeddingsPayload("eoc.pdf", "coverage")) == [0.25, -0.5]
    assert request["url"] == "https://openrouter.ai/api/v1/embeddings"
    assert request["headers"]["Authorization"] == "Bearer test-key"
    assert request["json"] == {
        "model": "openai/text-embedding-3-small",
        "input": ["coverage"],
    }


def test_worker_batches_page_embeddings(monkeypatch) -> None:
    batch_sizes = []

    def embed(texts):
        batch_sizes.append(len(texts))
        return [[float(index)] for index, _ in enumerate(texts)]

    monkeypatch.setattr("readforge.worker.embedding_model", lambda: "test/model")
    monkeypatch.setattr("readforge.worker.embed_texts", embed)
    pages = [
        OcrResponse(
            file_name="eoc.pdf",
            page_number=page,
            file_data={"text": f"Page {page}"},
        )
        for page in range(1, 34)
    ]

    chunks = _embed_pages(pages)

    assert batch_sizes == [32, 1]
    assert len(chunks) == 33
    assert all(chunk[2] == "test/model" for chunk in chunks)
