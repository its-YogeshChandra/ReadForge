"""Tests for Document AI batch OCR request construction and output parsing.

Google Document AI and Cloud Storage are faked; application request code is real.
Run with: uv run --with pytest pytest tests/test_document_ai.py -v
"""

from types import SimpleNamespace

import pytest
from google.cloud import documentai

import readforge.document_ai as api


class _Operation:
    operation = SimpleNamespace(name="projects/p/locations/us/operations/123")
    metadata = documentai.BatchProcessMetadata(
        state=documentai.BatchProcessMetadata.State.SUCCEEDED,
        individual_process_statuses=[
            {"output_gcs_destination": "gs://out/results/123/0/"}
        ],
    )

    def result(self, timeout: int) -> None:
        assert timeout == 30


class _DocumentClient:
    request = None
    endpoint = None

    def __init__(self, client_options):
        type(self).endpoint = client_options.api_endpoint

    def processor_path(self, project: str, location: str, processor: str) -> str:
        return f"projects/{project}/locations/{location}/processors/{processor}"

    def processor_version_path(self, *parts: str) -> str:
        return "/".join(parts)

    def batch_process_documents(self, request):
        type(self).request = request
        return _Operation()


class _Blob:
    name = "results/123/0/docai-1.json"

    def download_as_bytes(self) -> bytes:
        return b'{"text":"Recognized text"}'


class _StorageClient:
    def __init__(self, project: str):
        assert project == "project"

    def list_blobs(self, bucket: str, prefix: str):
        assert (bucket, prefix) == ("out", "results/123/0/")
        return [_Blob()]


@pytest.fixture
def google_clients(monkeypatch):
    monkeypatch.setattr(api.documentai, "DocumentProcessorServiceClient", _DocumentClient)
    monkeypatch.setattr(api.storage, "Client", _StorageClient)


# ═══════════════════════════════════════════════════════════════════════════
# 1. POSITIVE TESTS
# ═══════════════════════════════════════════════════════════════════════════


#what : Submits an explicit PDF through the regional Document AI batch endpoint.
#why   : The service must send GCS input, OCR options, and output configuration together.
def test_batch_ocr_explicit_document_returns_output_preview(google_clients) -> None:
    result = api.batch_process_documents(
        project_id="project",
        location="us",
        processor_id="processor",
        documents=[("gs://in/file.pdf", "application/pdf")],
        output_uri="gs://out/results",
        timeout=30,
        enable_math_ocr=True,
        compute_style_info=True,
    )

    request = _DocumentClient.request
    assert _DocumentClient.endpoint == "us-documentai.googleapis.com"
    assert request.input_documents.gcs_documents.documents[0].gcs_uri == "gs://in/file.pdf"
    assert request.document_output_config.gcs_output_config.gcs_uri == "gs://out/results/"
    assert request.process_options.ocr_config.premium_features.enable_math_ocr is True
    assert result == {
        "operation_name": "projects/p/locations/us/operations/123",
        "output_uris": ["gs://out/results/123/0/docai-1.json"],
        "previews": ["Recognized text"],
    }


#what : Submits every supported document under a GCS prefix.
#why   : Folder batches must use gcs_prefix instead of inventing per-file MIME types.
def test_batch_ocr_prefix_uses_gcs_prefix(google_clients) -> None:
    api.batch_process_documents(
        project_id="project",
        location="eu",
        processor_id="processor",
        input_prefix="gs://in/pdfs/",
        output_uri="gs://out/results/",
        timeout=30,
    )

    assert _DocumentClient.request.input_documents.gcs_prefix.gcs_uri_prefix == "gs://in/pdfs/"


# ═══════════════════════════════════════════════════════════════════════════
# 2. NEGATIVE TESTS
# ═══════════════════════════════════════════════════════════════════════════


#what : Rejects missing, conflicting, or malformed GCS input configuration.
#why   : Invalid batch locations must fail locally before creating a paid OCR operation.
@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({}, "Provide exactly one input_prefix or documents list"),
        (
            {
                "input_prefix": "gs://in/pdfs/",
                "documents": [("gs://in/file.pdf", "application/pdf")],
            },
            "Provide exactly one input_prefix or documents list",
        ),
        ({"input_prefix": "https://example.com/file.pdf"}, "Invalid GCS URI"),
        ({"documents": [("gs://in/file.pdf", "")]}, "MIME type is required"),
    ],
)
def test_batch_ocr_rejects_invalid_input(kwargs, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        api.batch_process_documents(
            project_id="project",
            location="us",
            processor_id="processor",
            output_uri="gs://out/results/",
            **kwargs,
        )


# ═══════════════════════════════════════════════════════════════════════════
# 3. SECURITY — documented gaps
# ═══════════════════════════════════════════════════════════════════════════

# SECURITY-1 : IAM and bucket access are enforced by Google ADC and Cloud Storage roles.
# SECURITY-2 : Do not accept project, processor, or bucket values directly from public clients.
