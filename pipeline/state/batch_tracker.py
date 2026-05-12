"""
Manages pipeline/state/batches.json — groups of 10 morning TopicRuns.
Each calendar day has at most one batch; refreshing the same day overwrites it.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..utils.logger import get_logger

logger = get_logger("batch_tracker")

BATCHES_FILE = Path(__file__).parent / "batches.json"
MAX_BATCHES_STORED = 30  # Keep one month of daily batches


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> dict:
    if not BATCHES_FILE.exists():
        return {"batches": []}
    try:
        return json.loads(BATCHES_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"batches": []}


def _save(data: dict) -> None:
    BATCHES_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# ── Public API ─────────────────────────────────────────────────────────────────


def get_today_batch() -> Optional[dict]:
    """Return today's batch dict, or None if not yet created."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for batch in _load()["batches"]:
        if batch["date"] == today:
            return batch
    return None


def get_batch_by_id(batch_id: str) -> Optional[dict]:
    for batch in _load()["batches"]:
        if batch["id"] == batch_id:
            return batch
    return None


def create_batch(topic_run_ids: list) -> dict:
    """
    Create (or replace) today's batch with the given run IDs.
    Returns the new batch dict.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    batch = {
        "id": f"batch_{today}",
        "date": today,
        "status": "ready_for_review",
        "topic_run_ids": topic_run_ids,
        "created_at": _now_iso(),
    }
    data = _load()
    # Remove any existing batch for today (refresh)
    data["batches"] = [b for b in data["batches"] if b["date"] != today]
    data["batches"].insert(0, batch)
    data["batches"] = data["batches"][:MAX_BATCHES_STORED]
    _save(data)
    logger.info(f"Created batch {batch['id']} with {len(topic_run_ids)} runs")
    return batch


def update_batch_status(batch_id: str, status: str) -> None:
    data = _load()
    for batch in data["batches"]:
        if batch["id"] == batch_id:
            batch["status"] = status
            break
    _save(data)


def add_run_to_batch(batch_id: str, run_id: str) -> None:
    """Append a run_id to an existing batch's topic_run_ids (idempotent)."""
    data = _load()
    for batch in data["batches"]:
        if batch["id"] == batch_id:
            ids: list = batch.setdefault("topic_run_ids", [])
            if run_id not in ids:
                ids.append(run_id)
            break
    _save(data)


def get_next_run_index(batch_id: str) -> int:
    """
    Return the next available run index for a batch.
    Scans existing topic_run_ids to find the highest t{NN} index already used.
    """
    import re
    batch = get_batch_by_id(batch_id)
    if not batch:
        return 0
    max_idx = -1
    for rid in batch.get("topic_run_ids", []):
        m = re.search(r"-t(\d+)$", rid)
        if m:
            max_idx = max(max_idx, int(m.group(1)))
    return max_idx + 1
