"""R2 download, PDF rendering, and macOS Vision OCR utilities."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from math import ceil, isfinite
import os
from pathlib import Path
import time
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv
import Quartz
import Vision

load_dotenv()

MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000


class PDFReadError(RuntimeError):
    """The PDF could not be downloaded or parsed safely."""


class PageRenderError(RuntimeError):
    """A PDF page could not be converted into an image."""


class OCRServiceError(RuntimeError):
    """Apple Vision could not OCR an image after retrying."""


@dataclass(frozen=True, slots=True)
class PdfPage:
    file_name: str
    page_number: int
    file_data: Any
    _document: Any = field(repr=False)


@dataclass(frozen=True, slots=True)
class OcrRequest:
    file_name: str
    page_number: int
    file_data: Any


@dataclass(frozen=True, slots=True)
class OcrResponse:
    file_name: str
    page_number: int
    file_data: dict[str, Any]


def _r2_client():
    """Create an R2 client from the standard Cloudflare credential variables."""
    account_id = os.getenv("ACCOUNT_ID")
    access_key = os.getenv("CLOUDFLARE_ACCESS_KEY")
    secret_key = os.getenv("CLOUDFLARE_SECRET_KEY")
    if not all((account_id, access_key, secret_key)):
        raise ValueError(
            "ACCOUNT_ID, CLOUDFLARE_ACCESS_KEY, and CLOUDFLARE_SECRET_KEY must be set"
        )

    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
    )


def _bucket_name() -> str:
    bucket = os.getenv("BUCKET_NAME")
    if not bucket:
        raise ValueError("BUCKET_NAME is not set")
    return bucket


async def is_file_exist(file_name: str) -> bool:
    """Return whether ``file_name`` exists in the configured R2 bucket.

    Missing-object responses return ``False``. Other R2 errors, such as
    authentication or network failures, are raised to the caller.
    """
    try:
        _r2_client().head_object(Bucket=_bucket_name(), Key=file_name)
        return True
    except ClientError as error:
        error_code = error.response.get("Error", {}).get("Code")
        status_code = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if error_code in {"404", "NoSuchKey", "NotFound"} or status_code == 404:
            return False
        raise


def download_files_from_s3(file_name: str, dest_folder: str) -> str:
    """Download an object from R2 to a local path and return that path."""
    dest = Path(dest_folder) / file_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    _r2_client().download_file(_bucket_name(), file_name, str(dest))
    return str(dest)


def create_presigned_url(file_name: str) -> str:
    """Create an R2 GET URL that is valid for one hour."""
    # check if file actually exist
    return _r2_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": _bucket_name(), "Key": file_name},
        ExpiresIn=3600,
    )


def list_objects() -> list[dict]:
    """List objects in the configured R2 bucket."""
    response = _r2_client().list_objects_v2(Bucket=_bucket_name())
    return response.get("Contents", [])


#take the file name and spits the size of the file out of that 
def get_file_size(file_name: str) -> int:
    """Return an R2 object's size in bytes without downloading it."""
    if not isinstance(file_name, str) or not file_name.strip():
        raise ValueError("file_name must not be empty")
    try:
        response = _r2_client().head_object(Bucket=_bucket_name(), Key=file_name)
    except (BotoCoreError, ClientError) as error:
        raise PDFReadError(f"Could not read size for '{file_name}'") from error
    size = response.get("ContentLength")
    if not isinstance(size, int) or size < 0:
        raise PDFReadError("R2 returned an invalid file size")
    return size


def download_page_from_pdf(
    file_name: str,
    *,
    file_data: bytes | bytearray | memoryview | None = None,
    max_file_size: int = MAX_PDF_BYTES,
) -> list[PdfPage]:
    """Load a PDF into memory and return its one-indexed Core Graphics pages."""
    if not isinstance(file_name, str) or not file_name.strip():
        raise ValueError("file_name must not be empty")
    if max_file_size <= 0:
        raise ValueError("max_file_size must be greater than zero")

    if file_data is None:
        try:
            response = _r2_client().get_object(Bucket=_bucket_name(), Key=file_name)
            size = response.get("ContentLength")
            if isinstance(size, int) and size > max_file_size:
                raise PDFReadError(
                    f"PDF is {size} bytes; maximum is {max_file_size} bytes"
                )
            body = response.get("Body")
            if body is None:
                raise PDFReadError("R2 response did not contain a file body")
            try:
                file_data = body.read(max_file_size + 1)
            finally:
                body.close()
        except PDFReadError:
            raise
        except (BotoCoreError, ClientError, OSError) as error:
            raise PDFReadError(f"Could not download PDF '{file_name}'") from error
    if not isinstance(file_data, (bytes, bytearray, memoryview)):
        raise TypeError("file_data must be bytes-like")

    pdf_data = bytes(file_data)
    if not pdf_data:
        raise PDFReadError("PDF is empty")
    if len(pdf_data) > max_file_size:
        raise PDFReadError(
            f"PDF is {len(pdf_data)} bytes; maximum is {max_file_size} bytes"
        )

    provider = Quartz.CGDataProviderCreateWithCFData(pdf_data)
    document = provider and Quartz.CGPDFDocumentCreateWithProvider(provider)
    if document is None:
        raise PDFReadError("File data is not a valid PDF")
    if Quartz.CGPDFDocumentIsEncrypted(document) and not Quartz.CGPDFDocumentIsUnlocked(
        document
    ):
        raise PDFReadError("Encrypted PDF requires a password")

    page_count = Quartz.CGPDFDocumentGetNumberOfPages(document)
    if page_count == 0:
        raise PDFReadError("PDF contains no pages")

    pages: list[PdfPage] = []
    for page_number in range(1, page_count + 1):
        page = Quartz.CGPDFDocumentGetPage(document, page_number)
        if page is None:
            raise PDFReadError(f"PDF page {page_number} could not be read")
        pages.append(PdfPage(file_name, page_number, page, document))
    return pages


def page_to_image(
    pages: Sequence[PdfPage],
    *,
    scale: float = 2.0,
    max_image_pixels: int = MAX_IMAGE_PIXELS,
) -> list[OcrRequest]:
    """Render PDF pages to CGImages suitable for Apple Vision."""
    if not pages:
        raise ValueError("At least one PDF page is required")
    if not isfinite(scale) or scale <= 0:
        raise ValueError("scale must be greater than zero")
    if max_image_pixels <= 0:
        raise ValueError("max_image_pixels must be greater than zero")

    # ponytail: this vector retains every bitmap; stream pages if large PDFs exceed memory.
    images: list[OcrRequest] = []
    color_space = Quartz.CGColorSpaceCreateDeviceRGB()
    for page in pages:
        if not isinstance(page, PdfPage):
            raise TypeError("pages must contain PdfPage values")
        bounds = Quartz.CGPDFPageGetBoxRect(page.file_data, Quartz.kCGPDFMediaBox)
        width = ceil(bounds.size.width * scale)
        height = ceil(bounds.size.height * scale)
        if width <= 0 or height <= 0:
            raise PageRenderError(f"PDF page {page.page_number} has invalid dimensions")
        if width * height > max_image_pixels:
            raise PageRenderError(
                f"PDF page {page.page_number} exceeds the {max_image_pixels}-pixel limit"
            )

        context = Quartz.CGBitmapContextCreate(
            None,
            width,
            height,
            8,
            0,
            color_space,
            Quartz.kCGImageAlphaPremultipliedLast,
        )
        if context is None:
            raise PageRenderError(f"Could not render PDF page {page.page_number}")

        Quartz.CGContextSetRGBFillColor(context, 1, 1, 1, 1)
        Quartz.CGContextFillRect(context, Quartz.CGRectMake(0, 0, width, height))
        Quartz.CGContextScaleCTM(context, scale, scale)
        Quartz.CGContextTranslateCTM(context, -bounds.origin.x, -bounds.origin.y)
        Quartz.CGContextDrawPDFPage(context, page.file_data)
        image = Quartz.CGBitmapContextCreateImage(context)
        if image is None:
            raise PageRenderError(f"Could not create image for PDF page {page.page_number}")
        images.append(OcrRequest(page.file_name, page.page_number, image))
    return images


def ocr_util(
    data: Sequence[OcrRequest], *, attempts: int = 3
) -> list[OcrResponse]:
    """OCR CGImages sequentially with Apple Vision, retrying transient failures."""
    if not data:
        raise ValueError("At least one OCR request is required")
    if attempts <= 0:
        raise ValueError("attempts must be greater than zero")

    responses: list[OcrResponse] = []
    for payload in data:
        if not isinstance(payload, OcrRequest):
            raise TypeError("data must contain OcrRequest values")
        if not isinstance(payload.file_name, str) or not payload.file_name.strip():
            raise ValueError("OCR request file_name must not be empty")
        if payload.page_number <= 0:
            raise ValueError("OCR request page_number must be greater than zero")
        if payload.file_data is None:
            raise ValueError(f"OCR page {payload.page_number} has no image data")

        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                request = Vision.VNRecognizeTextRequest.alloc().init()
                request.setRecognitionLevel_(
                    Vision.VNRequestTextRecognitionLevelAccurate
                )
                request.setUsesLanguageCorrection_(True)
                if hasattr(request, "setAutomaticallyDetectsLanguage_"):
                    request.setAutomaticallyDetectsLanguage_(True)

                handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(
                    payload.file_data, {}
                )
                succeeded, error = handler.performRequests_error_([request], None)
                if not succeeded:
                    message = error.localizedDescription() if error else "unknown error"
                    raise RuntimeError(message)

                lines = []
                for observation in request.results() or []:
                    candidates = observation.topCandidates_(1)
                    if candidates:
                        candidate = candidates[0]
                        lines.append(
                            {
                                "text": candidate.string(),
                                "confidence": float(candidate.confidence()),
                            }
                        )
                responses.append(
                    OcrResponse(
                        payload.file_name,
                        payload.page_number,
                        {
                            "text": "\n".join(line["text"] for line in lines),
                            "lines": lines,
                        },
                    )
                )
                break
            except Exception as error:
                last_error = error
                if attempt + 1 < attempts:
                    time.sleep(0.2 * (attempt + 1))
        else:
            raise OCRServiceError(
                f"Apple Vision failed for {payload.file_name} page "
                f"{payload.page_number} after {attempts} attempts"
            ) from last_error

    return responses
