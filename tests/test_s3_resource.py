"""Tests for fleet._async.resources.s3.S3Resource."""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from fleet._async.resources.s3 import S3Resource


class TestS3ResourceInit:
    """Test S3Resource initialization and URL parsing."""

    def test_init_with_s3_url(self):
        r = S3Resource(s3_url="s3://my-bucket/my-key/data.json")
        assert r.bucket == "my-bucket"
        assert r.key == "my-key/data.json"
        assert r.s3_url == "s3://my-bucket/my-key/data.json"

    def test_init_with_bucket_and_key(self):
        r = S3Resource(s3_url="", bucket="b", key="k/file.json")
        assert r.bucket == "b"
        assert r.key == "k/file.json"

    def test_init_with_s3_url_overrides_bucket_key(self):
        r = S3Resource(s3_url="s3://url-bucket/url-key.json", bucket="other", key="other")
        assert r.bucket == "url-bucket"
        assert r.key == "url-key.json"

    def test_init_missing_both_raises(self):
        with pytest.raises(ValueError, match="Either s3_url or both bucket and key"):
            S3Resource(s3_url="")

    def test_init_invalid_s3_url_no_prefix(self):
        with pytest.raises(ValueError, match="Invalid S3 URL format"):
            S3Resource(s3_url="https://bucket/key")

    def test_init_invalid_s3_url_no_key(self):
        with pytest.raises(ValueError, match="Invalid S3 URL format"):
            S3Resource(s3_url="s3://bucket-only")

    def test_content_type_default(self):
        r = S3Resource(s3_url="s3://b/k")
        assert r.content_type == "application/json"

    def test_content_type_custom(self):
        r = S3Resource(s3_url="s3://b/k", content_type="text/plain")
        assert r.content_type == "text/plain"

    def test_metadata(self):
        meta = {"size": 12345, "uploaded_at": "2026-01-01"}
        r = S3Resource(s3_url="s3://b/k", metadata=meta)
        assert r.metadata == meta

    def test_metadata_default_empty(self):
        r = S3Resource(s3_url="s3://b/k")
        assert r.metadata == {}


class TestS3ResourceSerialization:
    """Test to_dict / from_dict round-tripping."""

    def test_to_dict(self):
        r = S3Resource(
            s3_url="s3://bucket/prefix/data.json",
            content_type="application/json",
            metadata={"source": "test"},
        )
        d = r.to_dict()
        assert d == {
            "_type": "S3Resource",
            "s3_url": "s3://bucket/prefix/data.json",
            "content_type": "application/json",
            "metadata": {"source": "test"},
        }

    def test_from_dict(self):
        d = {
            "_type": "S3Resource",
            "s3_url": "s3://bucket/prefix/data.json",
            "content_type": "text/plain",
            "metadata": {"size": 999},
        }
        r = S3Resource.from_dict(d)
        assert r.s3_url == "s3://bucket/prefix/data.json"
        assert r.content_type == "text/plain"
        assert r.metadata == {"size": 999}

    def test_from_dict_roundtrip(self):
        original = S3Resource(
            s3_url="s3://b/k",
            content_type="application/json",
            metadata={"test": True},
        )
        d = original.to_dict()
        restored = S3Resource.from_dict(d)
        assert restored.s3_url == original.s3_url
        assert restored.content_type == original.content_type
        assert restored.metadata == original.metadata

    def test_from_dict_wrong_type_raises(self):
        with pytest.raises(ValueError, match="Expected dict with _type='S3Resource'"):
            S3Resource.from_dict({"_type": "NotS3Resource", "s3_url": "s3://b/k"})

    def test_from_dict_missing_type_raises(self):
        with pytest.raises(ValueError, match="Expected dict with _type='S3Resource'"):
            S3Resource.from_dict({"s3_url": "s3://b/k"})

    def test_is_s3_resource_dict_true(self):
        assert S3Resource.is_s3_resource_dict(
            {"_type": "S3Resource", "s3_url": "s3://b/k"}
        )

    def test_is_s3_resource_dict_false_wrong_type(self):
        assert not S3Resource.is_s3_resource_dict({"_type": "Other"})

    def test_is_s3_resource_dict_false_not_dict(self):
        assert not S3Resource.is_s3_resource_dict("not a dict")

    def test_is_s3_resource_dict_false_no_type(self):
        assert not S3Resource.is_s3_resource_dict({"s3_url": "s3://b/k"})


class TestS3ResourceDownload:
    """Test content access with mocked S3."""

    def _make_resource(self, content: bytes = b'{"messages": []}'):
        """Create an S3Resource with pre-cached content (no S3 needed)."""
        r = S3Resource(s3_url="s3://test-bucket/test-key.json")
        r._cached_bytes = content
        r._cached_content = None
        return r

    def test_content_property(self):
        r = self._make_resource(b'{"hello": "world"}')
        assert r.content == '{"hello": "world"}'

    def test_content_bytes_property(self):
        r = self._make_resource(b"raw bytes")
        assert r.content_bytes == b"raw bytes"

    def test_json_method(self):
        data = {"messages": [{"role": "user", "content": "hi"}]}
        r = self._make_resource(json.dumps(data).encode())
        assert r.json() == data

    def test_content_cached(self):
        r = self._make_resource(b"data")
        _ = r.content
        _ = r.content  # second access should use cache
        assert r._cached_content == "data"

    def test_len(self):
        r = self._make_resource(b"12345")
        assert len(r) == 5

    def test_download_to_file(self):
        r = self._make_resource(b"file content")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            path = f.name
        try:
            result = r.download(path)
            assert result == path
            with open(path, "rb") as f:
                assert f.read() == b"file content"
        finally:
            os.unlink(path)

    def test_download_temp(self):
        r = self._make_resource(b"temp content")
        path = r.download_temp(suffix=".json")
        try:
            with open(path, "rb") as f:
                assert f.read() == b"temp content"
            assert path.endswith(".json")
        finally:
            os.unlink(path)

    @patch("fleet._async.resources.s3.S3Resource._get_s3_client")
    def test_download_from_s3(self, mock_get_client):
        """Test that _download calls S3 correctly."""
        mock_body = MagicMock()
        mock_body.read.return_value = b'{"test": true}'
        mock_client = MagicMock()
        mock_client.get_object.return_value = {"Body": mock_body}
        mock_get_client.return_value = mock_client

        r = S3Resource(s3_url="s3://my-bucket/my-key.json")
        data = r._download()

        assert data == b'{"test": true}'
        mock_client.get_object.assert_called_once_with(
            Bucket="my-bucket", Key="my-key.json"
        )

    @patch("fleet._async.resources.s3.S3Resource._get_s3_client")
    def test_download_caches_result(self, mock_get_client):
        """Test that second call doesn't hit S3 again."""
        mock_body = MagicMock()
        mock_body.read.return_value = b"data"
        mock_client = MagicMock()
        mock_client.get_object.return_value = {"Body": mock_body}
        mock_get_client.return_value = mock_client

        r = S3Resource(s3_url="s3://b/k")
        r._download()
        r._download()  # second call

        # S3 should only be called once
        assert mock_client.get_object.call_count == 1


class TestS3ResourceRepr:
    """Test string representations."""

    def test_repr_no_cache(self):
        r = S3Resource(s3_url="s3://b/k")
        assert "s3://b/k" in repr(r)
        assert "size=" not in repr(r)

    def test_repr_with_cache(self):
        r = S3Resource(s3_url="s3://b/k")
        r._cached_bytes = b"12345"
        assert "size=5 bytes" in repr(r)

    def test_str(self):
        r = S3Resource(s3_url="s3://bucket/key")
        assert str(r) == "s3://bucket/key"
