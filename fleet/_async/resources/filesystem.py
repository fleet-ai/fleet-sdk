from typing import Any, Dict, List, Optional
from ...instance.models import (
    Resource as ResourceModel,
    FsDiffResponse,
    FsFileDiffEntry,
    FileStateRequest,
    FileStateResponse,
    FileStateTextRequest,
    DocTextRequest,
    DocMetadataRequest,
    DocMetadataResponse,
    DocStructuredRequest,
    DocStructuredResponse,
)
from .base import Resource

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..instance.base import AsyncWrapper


# Document extensions that need /fs/doc/text for readable content extraction
_DOC_EXTENSIONS = {
    ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls",
    ".xlsm", ".xltx", ".xltm",
    ".odt", ".ott", ".odm", ".ods", ".ots", ".odp", ".otp",
    ".odg", ".otg", ".odf",
    ".rtf", ".pdf", ".epub",
    ".xps", ".oxps", ".fb2", ".cbz", ".mobi",
}


def _is_doc_file(path: str) -> bool:
    lower = path.lower()
    return any(lower.endswith(ext) for ext in _DOC_EXTENSIONS)


class AsyncFilesystemDiff:
    """Wraps a filesystem diff response with assertion helpers."""

    def __init__(self, response: FsDiffResponse, resource: "AsyncFilesystemResource"):
        self.response = response
        self.files = response.files
        self.total_files = response.total_files
        self.total_size = response.total_size
        self._resource = resource

    def _files_by_path(self) -> Dict[str, FsFileDiffEntry]:
        return {f.path: f for f in self.files}

    def expect_no_changes(self) -> "AsyncFilesystemDiff":
        """Assert that no filesystem changes occurred."""
        if self.files:
            paths = [f.path for f in self.files]
            raise AssertionError(
                f"Expected no filesystem changes, but found {len(self.files)} changed file(s):\n"
                + "\n".join(f"  - {p}" for p in paths)
            )
        return self

    async def expect_only(self, allowed_changes: List[Dict[str, Any]]) -> "AsyncFilesystemDiff":
        """Assert that only the specified filesystem changes occurred.

        Each spec in allowed_changes is a dict with:
            - "path" (required): the file path to expect
            - "content" (optional): expected file content (exact match)
            - "content_contains" (optional): substring that must appear in content
            - "doc_text" (optional): expected extracted text from doc files (exact match)
            - "doc_text_contains" (optional): substring that must appear in doc text
            - "file_type" (optional): expected file_type value
            - "size" (optional): expected file size

        Use ... (Ellipsis) as a value to accept any value for that field.

        For document files (docx, pptx, xlsx, etc.), use doc_text / doc_text_contains
        instead of content / content_contains. These call /fs/doc/text to extract
        readable text from binary document formats.

        Raises:
            AssertionError: if unexpected files changed or specs don't match
        """
        if not allowed_changes:
            return self.expect_no_changes()

        files_by_path = self._files_by_path()
        allowed_paths = set()
        errors: List[str] = []

        for spec in allowed_changes:
            path = spec.get("path")
            if path is None:
                raise ValueError("Each allowed change spec must include a 'path' key")
            allowed_paths.add(path)

            if path not in files_by_path:
                errors.append(f"Expected change at '{path}' but file was not in diff")
                continue

            entry = files_by_path[path]
            await self._validate_entry(entry, spec, errors)

        # Check for unexpected changes
        unexpected = set(files_by_path.keys()) - allowed_paths
        if unexpected:
            errors.append(
                f"Unexpected filesystem changes ({len(unexpected)} file(s)):\n"
                + "\n".join(f"  - {p}" for p in sorted(unexpected))
            )

        if errors:
            raise AssertionError(
                f"Filesystem expect_only failed with {len(errors)} error(s):\n"
                + "\n".join(f"  {i+1}. {e}" for i, e in enumerate(errors))
            )

        return self

    async def expect_exactly(self, expected_changes: List[Dict[str, Any]]) -> "AsyncFilesystemDiff":
        """Assert that EXACTLY the specified filesystem changes occurred.

        Like expect_only, but also fails if an expected path is missing from the diff.
        See expect_only for the full spec format including doc_text / doc_text_contains.

        Raises:
            AssertionError: if changes don't match exactly
        """
        if not expected_changes and self.files:
            paths = [f.path for f in self.files]
            raise AssertionError(
                f"Expected no filesystem changes, but found {len(self.files)} changed file(s):\n"
                + "\n".join(f"  - {p}" for p in paths)
            )

        files_by_path = self._files_by_path()
        expected_paths = set()
        errors: List[str] = []

        for spec in expected_changes:
            path = spec.get("path")
            if path is None:
                raise ValueError("Each expected change spec must include a 'path' key")
            expected_paths.add(path)

            if path not in files_by_path:
                errors.append(f"Expected change at '{path}' but file was not in diff")
                continue

            entry = files_by_path[path]
            await self._validate_entry(entry, spec, errors)

        # Check for unexpected changes
        unexpected = set(files_by_path.keys()) - expected_paths
        if unexpected:
            errors.append(
                f"Unexpected filesystem changes ({len(unexpected)} file(s)):\n"
                + "\n".join(f"  - {p}" for p in sorted(unexpected))
            )

        # Check for missing expected changes
        missing = expected_paths - set(files_by_path.keys())
        if missing:
            errors.append(
                f"Missing expected filesystem changes ({len(missing)} file(s)):\n"
                + "\n".join(f"  - {p}" for p in sorted(missing))
            )

        if errors:
            raise AssertionError(
                f"Filesystem expect_exactly failed with {len(errors)} error(s):\n"
                + "\n".join(f"  {i+1}. {e}" for i, e in enumerate(errors))
            )

        return self

    async def _validate_entry(
        self, entry: FsFileDiffEntry, spec: Dict[str, Any], errors: List[str]
    ) -> None:
        path = spec["path"]

        # Plain content checks (for text files)
        if "content" in spec and spec["content"] is not ...:
            if entry.content is None:
                errors.append(f"'{path}': content not available (was content excluded from diff?)")
            elif entry.content != spec["content"]:
                errors.append(
                    f"'{path}': content mismatch\n"
                    f"    expected: {repr(spec['content'][:200])}\n"
                    f"    actual:   {repr(entry.content[:200])}"
                )

        if "content_contains" in spec and spec["content_contains"] is not ...:
            if entry.content is None:
                errors.append(f"'{path}': content not available for content_contains check")
            elif spec["content_contains"] not in entry.content:
                errors.append(
                    f"'{path}': content does not contain expected substring: "
                    f"{repr(spec['content_contains'][:200])}"
                )

        # Document text checks (for docx, pptx, xlsx, etc. via /fs/doc/text)
        if "doc_text" in spec or "doc_text_contains" in spec:
            try:
                doc_text = await self._resource.doc_text(path)
            except Exception as e:
                errors.append(f"'{path}': failed to extract doc text: {e}")
                doc_text = None

            if doc_text is not None:
                if "doc_text" in spec and spec["doc_text"] is not ...:
                    if doc_text != spec["doc_text"]:
                        errors.append(
                            f"'{path}': doc_text mismatch\n"
                            f"    expected: {repr(spec['doc_text'][:200])}\n"
                            f"    actual:   {repr(doc_text[:200])}"
                        )

                if "doc_text_contains" in spec and spec["doc_text_contains"] is not ...:
                    if spec["doc_text_contains"] not in doc_text:
                        errors.append(
                            f"'{path}': doc text does not contain expected substring: "
                            f"{repr(spec['doc_text_contains'][:200])}"
                        )

        if "file_type" in spec and spec["file_type"] is not ...:
            if entry.file_type != spec["file_type"]:
                errors.append(
                    f"'{path}': file_type mismatch (expected {spec['file_type']!r}, got {entry.file_type!r})"
                )

        if "size" in spec and spec["size"] is not ...:
            if entry.size != spec["size"]:
                errors.append(
                    f"'{path}': size mismatch (expected {spec['size']}, got {entry.size})"
                )


class AsyncFilesystemResource(Resource):
    """Filesystem resource that operates via the /diff/fs and /fs/* endpoints."""

    def __init__(self, resource: ResourceModel, client: "AsyncWrapper"):
        super().__init__(resource)
        self.client = client

    # ── Diff endpoints ────────────────────────────────────────────────

    async def diff(
        self,
        include_content: bool = True,
        max_content_size: int = 102400,
        exclude_patterns: Optional[List[str]] = None,
        extract_documents: bool = True,
    ) -> AsyncFilesystemDiff:
        """Get filesystem diff from the environment.

        Args:
            include_content: Kept for backwards compatibility, ignored by server
            max_content_size: Kept for backwards compatibility, ignored by server
            exclude_patterns: Kept for backwards compatibility, ignored by server
            extract_documents: Kept for backwards compatibility, ignored by server

        Returns:
            AsyncFilesystemDiff with assertion helpers
        """
        response = await self.client.request(
            "POST",
            "/diff/fs",
            json={},
        )
        result = response.json()
        fs_response = FsDiffResponse(**result)
        if not fs_response.success:
            raise RuntimeError(
                f"Filesystem diff failed: {fs_response.error or fs_response.message}"
            )
        return AsyncFilesystemDiff(fs_response, self)

    # ── Single file endpoints ─────────────────────────────────────────

    async def file(
        self,
        path: str,
        include_content: bool = True,
        max_content_size: int = 102400,
    ) -> FileStateResponse:
        """Get current state of a single file.

        Args:
            path: Absolute path to the file
            include_content: Whether to include file content (default True)
            max_content_size: Max file size to include content for (default 100KB)

        Returns:
            FileStateResponse with file metadata and optional content
        """
        request = FileStateRequest(
            path=path,
            include_content=include_content,
            max_content_size=max_content_size,
        )
        response = await self.client.request(
            "POST", "/fs/file", json=request.model_dump()
        )
        return FileStateResponse(**response.json())

    async def file_text(self, path: str, max_content_size: int = 102400) -> str:
        """Get file content as plain text.

        Args:
            path: Absolute path to the file
            max_content_size: Max file size (default 100KB)

        Returns:
            File content as string
        """
        request = FileStateTextRequest(
            path=path, max_content_size=max_content_size
        )
        response = await self.client.request(
            "POST", "/fs/file/text", json=request.model_dump()
        )
        return response.text

    # ── Document extraction endpoints ─────────────────────────────────

    async def doc_text(self, path: str, max_size: int = 10485760) -> str:
        """Extract plain text from a document file (docx, pptx, xlsx, pdf, etc.).

        Args:
            path: Absolute path to the document
            max_size: Max document size (default 10MB)

        Returns:
            Extracted text content as string
        """
        request = DocTextRequest(path=path, max_size=max_size)
        response = await self.client.request(
            "POST", "/fs/doc/text", json=request.model_dump()
        )
        return response.text

    async def doc_metadata(self, path: str) -> DocMetadataResponse:
        """Extract metadata from a document file.

        Args:
            path: Absolute path to the document

        Returns:
            DocMetadataResponse with file_type and metadata dict
        """
        request = DocMetadataRequest(path=path)
        response = await self.client.request(
            "POST", "/fs/doc/metadata", json=request.model_dump()
        )
        return DocMetadataResponse(**response.json())

    async def doc_structured(self, path: str) -> DocStructuredResponse:
        """Extract structured content from a document file.

        Args:
            path: Absolute path to the document

        Returns:
            DocStructuredResponse with file_type and structured data dict
        """
        request = DocStructuredRequest(path=path)
        response = await self.client.request(
            "POST", "/fs/doc/structured", json=request.model_dump()
        )
        return DocStructuredResponse(**response.json())
