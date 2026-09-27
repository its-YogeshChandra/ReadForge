"""Checks for the in-memory PDF → CGImage → Vision OCR pipeline."""

from types import SimpleNamespace

from Foundation import NSMutableData
import pytest
import Quartz

import readforge.utils.reading_util as reading


def _pdf_bytes() -> bytes:
    data = NSMutableData.data()
    consumer = Quartz.CGDataConsumerCreateWithCFData(data)
    context = Quartz.CGPDFContextCreate(consumer, ((0, 0), (200, 100)), None)
    Quartz.CGPDFContextBeginPage(context, None)
    Quartz.CGPDFContextEndPage(context)
    Quartz.CGPDFContextClose(context)
    return bytes(data)


def test_pdf_pages_render_to_images() -> None:
    pages = reading.download_page_from_pdf("test.pdf", file_data=_pdf_bytes())
    images = reading.page_to_image(pages)

    assert len(pages) == len(images) == 1
    assert images[0].page_number == 1
    assert Quartz.CGImageGetWidth(images[0].file_data) == 400
    assert Quartz.CGImageGetHeight(images[0].file_data) == 200


def test_ocr_retries_then_returns_json_compatible_output(monkeypatch) -> None:
    class Candidate:
        def string(self):
            return "Recognized text"

        def confidence(self):
            return 0.99

    class Observation:
        def topCandidates_(self, count):
            assert count == 1
            return [Candidate()]

    class Request:
        @classmethod
        def alloc(cls):
            return cls()

        def init(self):
            return self

        def setRecognitionLevel_(self, _level):
            pass

        def setUsesLanguageCorrection_(self, _enabled):
            pass

        def setAutomaticallyDetectsLanguage_(self, _enabled):
            pass

        def results(self):
            return [Observation()]

    class Handler:
        calls = 0

        @classmethod
        def alloc(cls):
            return cls()

        def initWithCGImage_options_(self, _image, _options):
            return self

        def performRequests_error_(self, _requests, _error):
            type(self).calls += 1
            return (type(self).calls == 3, None)

    monkeypatch.setattr(reading.Vision, "VNRecognizeTextRequest", Request)
    monkeypatch.setattr(reading.Vision, "VNImageRequestHandler", Handler)
    monkeypatch.setattr(reading.time, "sleep", lambda _seconds: None)

    result = reading.ocr_util([reading.OcrRequest("test.pdf", 1, object())])

    assert Handler.calls == 3
    assert result[0].file_data == {
        "text": "Recognized text",
        "lines": [{"text": "Recognized text", "confidence": pytest.approx(0.99)}],
    }


def test_pipeline_rejects_invalid_inputs() -> None:
    with pytest.raises(reading.PDFReadError, match="not a valid PDF"):
        reading.download_page_from_pdf("bad.pdf", file_data=b"not a pdf")
    with pytest.raises(ValueError, match="At least one PDF page"):
        reading.page_to_image([])
    with pytest.raises(ValueError, match="At least one OCR request"):
        reading.ocr_util([])


def test_get_file_size_uses_object_metadata(monkeypatch) -> None:
    client = SimpleNamespace(
        head_object=lambda **kwargs: {
            "ContentLength": 123,
            "request": kwargs,
        }
    )
    monkeypatch.setattr(reading, "_r2_client", lambda: client)
    monkeypatch.setattr(reading, "_bucket_name", lambda: "bucket")

    assert reading.get_file_size("file.pdf") == 123
