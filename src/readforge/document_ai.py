"""Google Document AI batch OCR for documents already staged in GCS."""

import argparse
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlsplit

from google.api_core.client_options import ClientOptions
from google.cloud import documentai, storage


def _split_gcs_uri(uri: str) -> tuple[str, str]:
    parsed = urlsplit(uri)
    if parsed.scheme != "gs" or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError(f"Invalid GCS URI: {uri}")
    return parsed.netloc, parsed.path.lstrip("/")


def batch_process_documents(
    *,
    project_id: str,
    location: str,
    processor_id: str,
    output_uri: str,
    input_prefix: str | None = None,
    documents: Sequence[tuple[str, str]] = (),
    processor_version: str | None = None,
    field_mask: str | None = None,
    timeout: int = 600,
    enable_math_ocr: bool = False,
    compute_style_info: bool = False,
) -> dict[str, Any]:
    """Run Enterprise Document OCR and return its operation and output previews."""
    if bool(input_prefix) == bool(documents):
        raise ValueError("Provide exactly one input_prefix or documents list")

    _split_gcs_uri(output_uri)
    output_uri = output_uri.rstrip("/") + "/"

    if input_prefix:
        _split_gcs_uri(input_prefix)
        input_config = documentai.BatchDocumentsInputConfig(
            gcs_prefix=documentai.GcsPrefix(gcs_uri_prefix=input_prefix)
        )
    else:
        gcs_documents = []
        for uri, mime_type in documents:
            _split_gcs_uri(uri)
            if not mime_type:
                raise ValueError(f"MIME type is required for {uri}")
            gcs_documents.append(
                documentai.GcsDocument(gcs_uri=uri, mime_type=mime_type)
            )
        input_config = documentai.BatchDocumentsInputConfig(
            gcs_documents=documentai.GcsDocuments(documents=gcs_documents)
        )

    output_options: dict[str, str] = {"gcs_uri": output_uri}
    if field_mask:
        output_options["field_mask"] = field_mask

    process_options = documentai.ProcessOptions(
        ocr_config=documentai.OcrConfig(
            enable_native_pdf_parsing=True,
            premium_features=documentai.OcrConfig.PremiumFeatures(
                enable_math_ocr=enable_math_ocr,
                compute_style_info=compute_style_info,
            ),
        )
    )
    client = documentai.DocumentProcessorServiceClient(
        client_options=ClientOptions(
            api_endpoint=f"{location}-documentai.googleapis.com"
        )
    )
    name = (
        client.processor_version_path(
            project_id, location, processor_id, processor_version
        )
        if processor_version
        else client.processor_path(project_id, location, processor_id)
    )
    request = documentai.BatchProcessRequest(
        name=name,
        input_documents=input_config,
        document_output_config=documentai.DocumentOutputConfig(
            gcs_output_config=documentai.DocumentOutputConfig.GcsOutputConfig(
                **output_options
            )
        ),
        skip_human_review=True,
        process_options=process_options,
    )

    operation = client.batch_process_documents(request=request)
    operation_name = operation.operation.name
    operation.result(timeout=timeout)
    metadata = documentai.BatchProcessMetadata(operation.metadata)
    if metadata.state != documentai.BatchProcessMetadata.State.SUCCEEDED:
        raise RuntimeError(f"Document AI batch failed: {metadata.state_message}")

    storage_client = storage.Client(project=project_id)
    output_uris: list[str] = []
    previews: list[str] = []
    for status in metadata.individual_process_statuses:
        if not status.output_gcs_destination:
            raise RuntimeError(f"Document AI input failed: {status.status.message}")
        bucket_name, prefix = _split_gcs_uri(status.output_gcs_destination)
        for blob in storage_client.list_blobs(bucket_name, prefix=prefix):
            if not blob.name.endswith(".json"):
                continue
            document = documentai.Document.from_json(
                blob.download_as_bytes(), ignore_unknown_fields=True
            )
            output_uris.append(f"gs://{bucket_name}/{blob.name}")
            previews.append(document.text[:200])

    return {
        "operation_name": operation_name,
        "output_uris": output_uris,
        "previews": previews,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Google Document AI batch OCR")
    parser.add_argument("--project", required=True)
    parser.add_argument("--location", required=True)
    parser.add_argument("--processor", required=True)
    parser.add_argument("--input", required=True, help="GCS file or prefix")
    parser.add_argument("--output", required=True, help="GCS output prefix")
    parser.add_argument("--mime", help="Required for a single input file")
    parser.add_argument("--processor-version")
    parser.add_argument("--field-mask")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--math", action="store_true")
    parser.add_argument("--styles", action="store_true")
    args = parser.parse_args()

    result = batch_process_documents(
        project_id=args.project,
        location=args.location,
        processor_id=args.processor,
        input_prefix=args.input if not args.mime else None,
        documents=[(args.input, args.mime)] if args.mime else (),
        output_uri=args.output,
        processor_version=args.processor_version,
        field_mask=args.field_mask,
        timeout=args.timeout,
        enable_math_ocr=args.math,
        compute_style_info=args.styles,
    )
    print(f"Operation: {result['operation_name']}")
    for uri, preview in zip(result["output_uris"], result["previews"], strict=True):
        print(f"{uri}\n{preview}")


if __name__ == "__main__":
    main()
