"""MCP tool definitions for Shell server.

Provides bash execution and file operations for Harbor integration.
"""

import asyncio
import base64
import logging
import os
from pathlib import Path
from typing import Callable

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

# Default timeout for bash commands (seconds)
DEFAULT_TIMEOUT = 120


def register_tools(mcp: FastMCP) -> None:
    """Register all shell tools with the MCP server.

    Args:
        mcp: FastMCP server instance
    """

    @mcp.tool()
    async def bash_exec(command: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
        """Execute a bash command and return the result.

        Args:
            command: The bash command to execute.
            timeout: Maximum execution time in seconds (default: 120).

        Returns:
            Dict with stdout, stderr, and return_code.
        """
        logger.info(f"bash_exec: {command[:100]}{'...' if len(command) > 100 else ''}")

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=os.environ.get("SHELL_WORKDIR", "/"),
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                logger.warning(f"bash_exec timed out after {timeout}s")
                return {
                    "stdout": "",
                    "stderr": f"Command timed out after {timeout} seconds",
                    "return_code": -1,
                }

            result = {
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "return_code": proc.returncode,
            }
            logger.info(f"bash_exec completed: return_code={proc.returncode}")
            return result

        except Exception as e:
            logger.error(f"bash_exec failed: {type(e).__name__}: {e}")
            return {
                "stdout": "",
                "stderr": str(e),
                "return_code": -1,
            }

    @mcp.tool()
    async def file_read(path: str) -> dict:
        """Read the contents of a file.

        Args:
            path: Absolute path to the file to read.

        Returns:
            Dict with content (text or base64 for binary) and metadata.
        """
        logger.info(f"file_read: {path}")

        try:
            file_path = Path(path)
            if not file_path.exists():
                return {"error": f"File not found: {path}"}

            if not file_path.is_file():
                return {"error": f"Not a file: {path}"}

            # Try to read as text first
            try:
                content = file_path.read_text()
                return {
                    "content": content,
                    "encoding": "text",
                    "size": len(content),
                }
            except UnicodeDecodeError:
                # Binary file - return as base64
                binary_content = file_path.read_bytes()
                return {
                    "content": base64.b64encode(binary_content).decode("ascii"),
                    "encoding": "base64",
                    "size": len(binary_content),
                }

        except PermissionError:
            logger.warning(f"file_read permission denied: {path}")
            return {"error": f"Permission denied: {path}"}
        except Exception as e:
            logger.error(f"file_read failed: {type(e).__name__}: {e}")
            return {"error": str(e)}

    @mcp.tool()
    async def file_write(path: str, content: str, encoding: str = "text") -> dict:
        """Write content to a file.

        Args:
            path: Absolute path to the file to write.
            content: Content to write (text or base64-encoded for binary).
            encoding: "text" for text content, "base64" for binary content.

        Returns:
            Dict with success status and metadata.
        """
        logger.info(f"file_write: {path} (encoding={encoding})")

        try:
            file_path = Path(path)

            # Create parent directories if needed
            file_path.parent.mkdir(parents=True, exist_ok=True)

            if encoding == "base64":
                binary_content = base64.b64decode(content)
                file_path.write_bytes(binary_content)
                size = len(binary_content)
            else:
                file_path.write_text(content)
                size = len(content)

            return {
                "success": True,
                "path": str(file_path.absolute()),
                "size": size,
            }

        except PermissionError:
            logger.warning(f"file_write permission denied: {path}")
            return {"error": f"Permission denied: {path}"}
        except Exception as e:
            logger.error(f"file_write failed: {type(e).__name__}: {e}")
            return {"error": str(e)}

    @mcp.tool()
    async def file_list(path: str) -> dict:
        """List contents of a directory.

        Args:
            path: Absolute path to the directory.

        Returns:
            Dict with list of files and directories.
        """
        logger.info(f"file_list: {path}")

        try:
            dir_path = Path(path)
            if not dir_path.exists():
                return {"error": f"Directory not found: {path}"}

            if not dir_path.is_dir():
                return {"error": f"Not a directory: {path}"}

            entries = []
            for entry in dir_path.iterdir():
                entries.append({
                    "name": entry.name,
                    "type": "directory" if entry.is_dir() else "file",
                    "size": entry.stat().st_size if entry.is_file() else None,
                })

            return {
                "path": str(dir_path.absolute()),
                "entries": entries,
                "count": len(entries),
            }

        except PermissionError:
            logger.warning(f"file_list permission denied: {path}")
            return {"error": f"Permission denied: {path}"}
        except Exception as e:
            logger.error(f"file_list failed: {type(e).__name__}: {e}")
            return {"error": str(e)}

    @mcp.tool()
    async def file_delete(path: str) -> dict:
        """Delete a file or empty directory.

        Args:
            path: Absolute path to the file or directory to delete.

        Returns:
            Dict with success status.
        """
        logger.info(f"file_delete: {path}")

        try:
            file_path = Path(path)
            if not file_path.exists():
                return {"error": f"Path not found: {path}"}

            if file_path.is_dir():
                file_path.rmdir()  # Only works for empty directories
            else:
                file_path.unlink()

            return {"success": True, "path": str(file_path.absolute())}

        except OSError as e:
            if "not empty" in str(e).lower():
                return {"error": f"Directory not empty: {path}"}
            return {"error": str(e)}
        except PermissionError:
            logger.warning(f"file_delete permission denied: {path}")
            return {"error": f"Permission denied: {path}"}
        except Exception as e:
            logger.error(f"file_delete failed: {type(e).__name__}: {e}")
            return {"error": str(e)}
