"""Provider selection checks for the media bucket facade."""

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
    assert client.meta.config.s3["addressing_style"] == "path"
    assert minio_storage.get_bucket_name() == "documents"
    minio_storage.get_client.cache_clear()
