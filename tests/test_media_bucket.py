"""Provider selection checks for the media bucket facade."""

from botocore.exceptions import ClientError
import pytest

from readforge.utils import media_bucket, minio_storage


def test_media_bucket_provider_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    cloudflare_client = object()
    minio_client = object()
    monkeypatch.setattr(
        media_bucket.cloudflare_r2, "get_client", lambda: cloudflare_client
    )
    monkeypatch.setattr(
        media_bucket.cloudflare_r2, "get_bucket_name", lambda: "r2-bucket"
    )
    monkeypatch.setattr(
        media_bucket.minio_storage, "get_client", lambda: minio_client
    )
    monkeypatch.setattr(
        media_bucket.minio_storage, "get_bucket_name", lambda: "minio-bucket"
    )

    monkeypatch.delenv("MEDIA_BUCKET_PROVIDER", raising=False)
    assert media_bucket.get_client() is cloudflare_client
    assert media_bucket.get_bucket_name() == "r2-bucket"

    monkeypatch.setenv("MEDIA_BUCKET_PROVIDER", "minio")
    assert media_bucket.get_client() is minio_client
    assert media_bucket.get_bucket_name() == "minio-bucket"

    monkeypatch.setenv("MEDIA_BUCKET_PROVIDER", "unknown")
    with pytest.raises(ValueError, match="MEDIA_BUCKET_PROVIDER"):
        media_bucket.get_client()


def test_minio_uses_s3_endpoint_and_path_style(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MINIO_ENDPOINT", "http://127.0.0.1:9000")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "access")
    monkeypatch.setenv("MINIO_SECRET_KEY", "secret")
    monkeypatch.setenv("MINIO_BUCKET_NAME", "documents")
    minio_storage.get_client.cache_clear()

    client = minio_storage.get_client()

    assert client.meta.endpoint_url == "http://127.0.0.1:9000"
    assert client.meta.region_name == "us-east-1"
    assert client.meta.config.s3["addressing_style"] == "path"
    assert minio_storage.get_bucket_name() == "documents"
    minio_storage.get_client.cache_clear()


def test_media_bucket_health_check_uses_selected_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class Client:
        def head_bucket(self, *, Bucket: str) -> None:
            calls.append(Bucket)

    monkeypatch.setattr(media_bucket, "get_client", Client)
    monkeypatch.setattr(media_bucket, "get_bucket_name", lambda: "documents")

    media_bucket.ensure_available()

    assert calls == ["documents"]


def test_media_bucket_health_failure_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = ClientError(
        {
            "Error": {"Code": "AccessDenied", "Message": "denied"},
            "ResponseMetadata": {"HTTPStatusCode": 403},
        },
        "HeadBucket",
    )

    class Client:
        def head_bucket(self, **_kwargs) -> None:
            raise error

    monkeypatch.setattr(media_bucket, "get_client", Client)
    monkeypatch.setattr(media_bucket, "get_bucket_name", lambda: "documents")

    with pytest.raises(media_bucket.MediaBucketUnavailableError):
        media_bucket.ensure_available()


def test_storage_errors_distinguish_unavailable_from_rejected() -> None:
    unavailable = ClientError(
        {
            "Error": {"Code": "ServiceUnavailable", "Message": "retry"},
            "ResponseMetadata": {"HTTPStatusCode": 503},
        },
        "PutObject",
    )
    rejected = ClientError(
        {
            "Error": {"Code": "InvalidDigest", "Message": "invalid"},
            "ResponseMetadata": {"HTTPStatusCode": 400},
        },
        "PutObject",
    )

    assert media_bucket.is_unavailable_error(unavailable) is True
    assert media_bucket.is_unavailable_error(rejected) is False
