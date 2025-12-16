"""Raw traffic uploader - spools proxy logs and uploads to backend.

No parsing, no structuring - just batch and ship raw entries.
Backend handles all parsing/extraction of transcripts.

Usage:
    uploader = TrafficUploader(job_id="eval_123", log_file=proxy.log_path)
    await uploader.start()  # Starts tailing and uploading
    # ... run tasks ...
    await uploader.stop()   # Flushes remaining
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import List, Optional, Set

logger = logging.getLogger(__name__)


class TrafficUploader:
    """Tails proxy log file and uploads raw entries in batches.
    
    Design:
    - Tails JSONL file (like tail -f)
    - Batches by count (100) or time (500ms)
    - Uploads raw JSON entries (no parsing)
    - Optional URL whitelist for filtering
    """
    
    BATCH_SIZE = 100
    FLUSH_INTERVAL_MS = 500
    UPLOAD_TIMEOUT = 10.0
    MAX_RETRIES = 3
    
    def __init__(
        self,
        job_id: str,
        log_file: Path,
        whitelist: Optional[Set[str]] = None,
    ):
        self.job_id = job_id
        self.log_file = log_file
        self.whitelist = whitelist  # URL patterns to include (None = all)
        
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._file = None
        self._position = 0
        
        # Stats
        self._read = 0
        self._uploaded = 0
        self._filtered = 0
        
        # HTTP client
        self._client = None
        self._base_url = os.environ.get("FLEET_API_URL", "https://orchestrator.fleetai.com")
        self._api_key = os.environ.get("FLEET_API_KEY", "")
    
    async def start(self):
        """Start tailing and uploading."""
        if self._running:
            return
        
        self._running = True
        self._position = 0
        self._read = 0
        self._uploaded = 0
        self._filtered = 0
        
        # Start tail loop
        self._task = asyncio.create_task(self._tail_loop())
        logger.info(f"Uploader started: job={self.job_id}, file={self.log_file}")
    
    async def stop(self):
        """Stop and flush remaining entries."""
        if not self._running:
            return
        
        self._running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        # Final read and upload
        entries = self._read_new_entries()
        if entries:
            await self._upload_batch(entries)
        
        # Close client
        if self._client:
            await self._client.aclose()
            self._client = None
        
        logger.info(f"Uploader stopped: read={self._read}, uploaded={self._uploaded}, filtered={self._filtered}")
    
    async def _tail_loop(self):
        """Main loop - tail file and upload batches."""
        batch: List[dict] = []
        last_flush = time.time()
        
        while self._running:
            try:
                # Read new entries from file
                new_entries = self._read_new_entries()
                
                for entry in new_entries:
                    # Apply whitelist filter
                    if self._should_include(entry):
                        batch.append(entry)
                    else:
                        self._filtered += 1
                
                # Check if we should flush
                now = time.time()
                should_flush = (
                    len(batch) >= self.BATCH_SIZE or
                    (batch and (now - last_flush) * 1000 >= self.FLUSH_INTERVAL_MS)
                )
                
                if should_flush:
                    await self._upload_batch(batch)
                    batch = []
                    last_flush = now
                
                # Small sleep to avoid busy loop
                await asyncio.sleep(0.05)  # 50ms
                
            except asyncio.CancelledError:
                # Upload remaining on cancel
                if batch:
                    await self._upload_batch(batch)
                raise
            except Exception as e:
                logger.error(f"Tail loop error: {e}")
                await asyncio.sleep(1)
    
    def _read_new_entries(self) -> List[dict]:
        """Read new lines from log file."""
        entries = []
        
        try:
            if not self.log_file.exists():
                return entries
            
            with open(self.log_file, "r") as f:
                f.seek(self._position)
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entry = json.loads(line)
                            entries.append(entry)
                            self._read += 1
                        except json.JSONDecodeError:
                            pass
                self._position = f.tell()
        except Exception as e:
            logger.error(f"Read error: {e}")
        
        return entries
    
    def _should_include(self, entry: dict) -> bool:
        """Check if entry passes whitelist filter."""
        if self.whitelist is None:
            return True  # No filter, include all
        
        # Check URL against whitelist patterns
        url = entry.get("request", {}).get("url", "")
        for pattern in self.whitelist:
            if pattern in url:
                return True
        
        return False
    
    async def _upload_batch(self, batch: List[dict]):
        """Upload batch of raw entries to backend."""
        if not batch:
            return
        
        if not self._api_key:
            # No API key, just count as uploaded (data is in local file)
            self._uploaded += len(batch)
            return
        
        for attempt in range(self.MAX_RETRIES):
            try:
                await self._do_upload(batch)
                self._uploaded += len(batch)
                return
            except Exception as e:
                if attempt == self.MAX_RETRIES - 1:
                    logger.warning(f"Upload failed after {self.MAX_RETRIES} attempts: {e}")
                else:
                    await asyncio.sleep(0.2 * (attempt + 1))
    
    async def _do_upload(self, batch: List[dict]):
        """POST raw entries to backend."""
        import httpx
        
        if not self._client:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self.UPLOAD_TIMEOUT,
            )
        
        payload = {
            "job_id": self.job_id,
            "entries": batch,  # Raw entries, no parsing
        }
        
        resp = await self._client.post(f"/v1/eval_jobs/{self.job_id}/logs", json=payload)
        resp.raise_for_status()
    
    @property
    def stats(self) -> dict:
        return {
            "read": self._read,
            "uploaded": self._uploaded,
            "filtered": self._filtered,
        }

