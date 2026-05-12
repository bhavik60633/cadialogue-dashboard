"""
In-memory SSE pub/sub and job registry for the FastAPI pipeline service.
State is ephemeral — only persists while the uvicorn process is running.
"""
import asyncio
import json
from typing import Dict, List, Optional


class SSEPublisher:
    """Manages Server-Sent Events subscriptions per run_id."""

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[asyncio.Queue]] = {}

    def subscribe(self, run_id: str, queue: asyncio.Queue) -> None:
        self._subscribers.setdefault(run_id, []).append(queue)

    def unsubscribe(self, run_id: str, queue: asyncio.Queue) -> None:
        if run_id in self._subscribers:
            try:
                self._subscribers[run_id].remove(queue)
            except ValueError:
                pass
            if not self._subscribers[run_id]:
                del self._subscribers[run_id]

    async def publish(self, run_id: str, data: dict) -> None:
        """Broadcast a dict payload to all subscribers of run_id."""
        if run_id not in self._subscribers:
            return
        message = json.dumps(data)
        for queue in list(self._subscribers[run_id]):
            await queue.put(message)

    async def close(self, run_id: str) -> None:
        """Signal end-of-stream to all subscribers."""
        if run_id not in self._subscribers:
            return
        for queue in list(self._subscribers[run_id]):
            await queue.put(None)
        del self._subscribers[run_id]

    def subscriber_count(self, run_id: str) -> int:
        return len(self._subscribers.get(run_id, []))


class JobRegistry:
    """Tracks background asyncio tasks so we can detect duplicate requests."""

    def __init__(self) -> None:
        self._jobs: Dict[str, dict] = {}

    def register(self, job_id: str, task: asyncio.Task, run_id: str) -> None:
        self._jobs[job_id] = {"task": task, "run_id": run_id}

    def get(self, job_id: str) -> Optional[dict]:
        return self._jobs.get(job_id)

    def is_running(self, run_id: str) -> bool:
        """Return True if any active task is processing the given run_id."""
        for job in self._jobs.values():
            if job["run_id"] == run_id and not job["task"].done():
                return True
        return False

    def cleanup_done(self) -> None:
        """Remove completed/cancelled tasks to free memory."""
        done_ids = [jid for jid, j in self._jobs.items() if j["task"].done()]
        for jid in done_ids:
            del self._jobs[jid]


# Module-level singletons
sse_publisher = SSEPublisher()
job_registry = JobRegistry()
