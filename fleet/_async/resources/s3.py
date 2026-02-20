"""Fleet SDK S3 Resource.

Provides an S3Resource class that wraps an S3 URL and transparently
downloads the content when accessed. Used to pass large payloads
(e.g., conversation transcripts) to verifiers without exceeding
HTTP/Temporal payload size limits.

The harness uploads large data to S3 and passes the S3 URL as an
S3Resource to the verifier. The verifier accesses the content via
the resource, which downloads it on first access and caches locally.
"""

import json
import logging
import os
import tempfile
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


class S3Resource:
    """A resource backed by an S3 object.

    Wraps an S3 URL (s3://bucket/key) and provides transparent access
    to the underlying content. Content is downloaded lazily on first
    access and cached locally.

    This is used by the harness to pass large payloads to verifiers:
    instead of including a 200MB transcript in the Temporal activity
    params, the harness uploads it to S3 and passes an S3Resource.

    The verifier can then access the data as if it were a local object:
        - resource.content       -> raw string content
        - resource.json()        -> parsed JSON
        - resource.download(path) -> download to local file

    Example:
        # In a verifier function:
        def verify(env, conversation: S3Resource) -> float:
            messages = conversation.json()
            last_msg = messages[-1]
            # ... verify based on conversation content ...
            return 1.0
    """

    def __init__(
        self,
        s3_url: str,
        *,
        bucket: Optional[str] = None,
        key: Optional[str] = None,
        content_type: str = "application/json",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Initialize S3Resource.

        Args:
            s3_url: Full S3 URL (s3://bucket/key). If provided, bucket
                    and key are extracted from it.
            bucket: S3 bucket name (alternative to s3_url).
            key: S3 object key (alternative to s3_url).
            content_type: Expected content type of the S3 object.
            metadata: Optional metadata about the resource (e.g., original
                      size, upload timestamp).
        """
        if s3_url:
            self._bucket, self._key = self._parse_s3_url(s3_url)
        elif bucket and key:
            self._bucket = bucket
            self._key = key
        else:
            raise ValueError("Either s3_url or both bucket and key must be provided")

        self._content_type = content_type
        self._metadata = metadata or {}
        self._cached_content: Optional[str] = None
        self._cached_bytes: Optional[bytes] = None

    @staticmethod
    def _parse_s3_url(s3_url: str) -> tuple:
        """Parse an s3://bucket/key URL into (bucket, key)."""
        if not s3_url.startswith("s3://"):
            raise ValueError(f"Invalid S3 URL format (expected s3://...): {s3_url}")
        path = s3_url[5:]  # Remove "s3://"
        parts = path.split("/", 1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise ValueError(f"Invalid S3 URL format: {s3_url}")
        return parts[0], parts[1]

    @property
    def s3_url(self) -> str:
        """Full S3 URL."""
        return f"s3://{self._bucket}/{self._key}"

    @property
    def bucket(self) -> str:
        """S3 bucket name."""
        return self._bucket

    @property
    def key(self) -> str:
        """S3 object key."""
        return self._key

    @property
    def content_type(self) -> str:
        """Expected content type."""
        return self._content_type

    @property
    def metadata(self) -> Dict[str, Any]:
        """Resource metadata."""
        return self._metadata

    def _get_s3_client(self):
        """Get a boto3 S3 client."""
        try:
            import boto3
            from botocore.config import Config

            s3_config = Config(
                retries={"max_attempts": 3, "mode": "adaptive"},
            )
            region = os.getenv("AWS_REGION", "us-west-1")
            return boto3.client("s3", region_name=region, config=s3_config)
        except ImportError:
            raise ImportError(
                "boto3 is required for S3Resource. "
                "Install it with: pip install boto3"
            )

    def _download(self) -> bytes:
        """Download content from S3 (cached)."""
        if self._cached_bytes is not None:
            return self._cached_bytes

        s3_client = self._get_s3_client()
        try:
            response = s3_client.get_object(Bucket=self._bucket, Key=self._key)
            self._cached_bytes = response["Body"].read()
            logger.info(
                f"[S3Resource] Downloaded {len(self._cached_bytes)} bytes "
                f"from {self.s3_url}"
            )
            return self._cached_bytes
        except Exception as e:
            logger.error(f"[S3Resource] Failed to download {self.s3_url}: {e}")
            raise

    @property
    def content(self) -> str:
        """Get content as a UTF-8 string (downloaded lazily, cached)."""
        if self._cached_content is not None:
            return self._cached_content
        data = self._download()
        self._cached_content = data.decode("utf-8")
        return self._cached_content

    @property
    def content_bytes(self) -> bytes:
        """Get raw bytes content (downloaded lazily, cached)."""
        return self._download()

    def json(self) -> Any:
        """Parse content as JSON and return the result."""
        return json.loads(self.content)

    def download(self, path: str) -> str:
        """Download the S3 object to a local file path.

        Args:
            path: Local file path to save to.

        Returns:
            The path written to.
        """
        data = self._download()
        with open(path, "wb") as f:
            f.write(data)
        logger.info(f"[S3Resource] Saved {len(data)} bytes to {path}")
        return path

    def download_temp(self, suffix: Optional[str] = None) -> str:
        """Download to a temporary file and return the path.

        Args:
            suffix: Optional file suffix (e.g., '.json').

        Returns:
            Path to the temporary file.
        """
        data = self._download()
        fd, path = tempfile.mkstemp(suffix=suffix or ".tmp")
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        logger.info(f"[S3Resource] Saved {len(data)} bytes to temp file {path}")
        return path

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a dict (for passing through Temporal/JSON).

        The dict includes a type marker so the harness/SDK can
        reconstruct the S3Resource on the other side.
        """
        return {
            "_type": "S3Resource",
            "s3_url": self.s3_url,
            "content_type": self._content_type,
            "metadata": self._metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "S3Resource":
        """Reconstruct an S3Resource from a serialized dict.

        Args:
            data: Dict with s3_url, content_type, and metadata keys.

        Returns:
            S3Resource instance.
        """
        if data.get("_type") != "S3Resource":
            raise ValueError(
                f"Expected dict with _type='S3Resource', got {data.get('_type')}"
            )
        return cls(
            s3_url=data["s3_url"],
            content_type=data.get("content_type", "application/json"),
            metadata=data.get("metadata"),
        )

    @classmethod
    def is_s3_resource_dict(cls, data: Any) -> bool:
        """Check if a dict looks like a serialized S3Resource."""
        return isinstance(data, dict) and data.get("_type") == "S3Resource"

    def __repr__(self) -> str:
        size_info = ""
        if self._cached_bytes is not None:
            size_info = f", size={len(self._cached_bytes)} bytes"
        return f"S3Resource(s3_url={self.s3_url!r}{size_info})"

    def __str__(self) -> str:
        return self.s3_url

    def __len__(self) -> int:
        """Return content length in bytes."""
        return len(self._download())
