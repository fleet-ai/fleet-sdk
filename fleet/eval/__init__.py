"""Eval telemetry - uploads raw proxy traffic to backend.

Simple design:
- Proxy captures all HTTP traffic to JSONL file
- Uploader tails file, batches entries, ships raw to backend
- Backend does all parsing/structuring of transcripts
- Optional whitelist to filter URLs

No local parsing - just spool and ship.
"""

from .uploader import TrafficUploader

__all__ = ["TrafficUploader"]

