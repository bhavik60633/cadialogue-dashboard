"""
Manages pipeline/state/runs.json — the single source of truth for all pipeline runs.
This file is committed by GitHub Actions after each run and read by the Next.js dashboard.
"""
import json
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..utils.logger import get_logger

logger = get_logger("run_tracker")

RUNS_FILE = Path(__file__).parent / "runs.json"
MAX_RUNS_STORED = 90  # Keep 90 days of history


@dataclass
class LogEntry:
    timestamp: str
    level: str          # "info" | "warning" | "error"
    stage: str
    message: str


@dataclass
class PipelineRun:
    id: str
    started_at: str
    completed_at: Optional[str] = None
    status: str = "running"         # "running"|"completed"|"failed"|"pending_approval"
    stage: str = "init"
    topic: Optional[str] = None
    article_word_count: Optional[int] = None
    wp_post_id: Optional[int] = None
    wp_post_url: Optional[str] = None
    approval_status: str = "pending"  # "pending"|"approved"|"rejected"|"auto_approved"|"draft_saved"
    error: Optional[str] = None
    log_entries: list = field(default_factory=list)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_all() -> list[dict]:
    if not RUNS_FILE.exists():
        return []
    try:
        return json.loads(RUNS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_all(runs: list[dict]) -> None:
    RUNS_FILE.write_text(json.dumps(runs, indent=2, ensure_ascii=False), encoding="utf-8")


def _generate_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


# ── Public API ─────────────────────────────────────────────────────────────────

def init_run() -> str:
    """Create a new run entry and return its ID."""
    run_id = _generate_run_id()
    run = PipelineRun(id=run_id, started_at=_now_iso())
    _append_log(run, "info", "init", "Pipeline started")

    runs = _load_all()
    runs.insert(0, asdict(run))       # newest first
    runs = runs[:MAX_RUNS_STORED]
    _save_all(runs)

    logger.info(f"Initialized run {run_id}")
    return run_id


def update_run(run_id: str, **kwargs) -> None:
    """Update fields on an existing run."""
    runs = _load_all()
    for run in runs:
        if run["id"] == run_id:
            run.update(kwargs)
            break
    _save_all(runs)


def log(run_id: str, level: str, stage: str, message: str) -> None:
    """Append a log entry to the run and print it."""
    runs = _load_all()
    entry = asdict(LogEntry(timestamp=_now_iso(), level=level, stage=stage, message=message))
    for run in runs:
        if run["id"] == run_id:
            run.setdefault("log_entries", []).append(entry)
            run["stage"] = stage
            break
    _save_all(runs)

    level_fn = getattr(logger, level, logger.info)
    level_fn(f"[{stage}] {message}")


def complete_run(run_id: str, wp_post_url: str) -> None:
    update_run(
        run_id,
        status="completed",
        completed_at=_now_iso(),
        wp_post_url=wp_post_url,
    )
    logger.info(f"Run {run_id} completed → {wp_post_url}")


def fail_run(run_id: str, error: str) -> None:
    update_run(
        run_id,
        status="failed",
        completed_at=_now_iso(),
        error=error,
    )
    logger.error(f"Run {run_id} FAILED: {error}")


def load_run(run_id: str) -> Optional[dict]:
    for run in _load_all():
        if run["id"] == run_id:
            return run
    return None


def load_all_runs() -> list[dict]:
    return _load_all()


# ── Dashboard batch extensions ──────────────────────────────────────────────────

def init_topic_run(batch_id: str, topic_meta: dict, run_index: int = 0) -> str:
    """
    Create a TopicRun entry for a morning batch topic.
    Returns the new run ID.
    Run IDs use the pattern: YYYY-MM-DD-tNN  (e.g. 2026-05-07-t03)
    """
    date_part = batch_id.replace("batch_", "")  # "2026-05-07"
    run_id = f"{date_part}-t{run_index:02d}"

    run = {
        "id": run_id,
        "batch_id": batch_id,
        "started_at": _now_iso(),
        "completed_at": None,
        "status": "pending_approval",
        "stage": "init",
        "topic": topic_meta.get("title"),
        "article_word_count": None,
        "wp_post_id": None,
        "wp_post_url": None,
        "approval_status": "pending",
        "error": None,
        "log_entries": [],
        # Dashboard-only fields
        "topic_status": "pending",
        "topic_meta": topic_meta,
        "article_sections": None,
        "images": None,
    }

    runs = _load_all()
    # Remove any existing run with same ID (idempotent re-creation on batch refresh)
    runs = [r for r in runs if r.get("id") != run_id]
    runs.insert(0, run)
    runs = runs[:MAX_RUNS_STORED]
    _save_all(runs)

    logger.info(f"Initialized topic run {run_id} for batch {batch_id}")
    return run_id


def update_topic_status(run_id: str, topic_status: str) -> None:
    """Shorthand: update just the topic_status field."""
    update_run(run_id, topic_status=topic_status)


def delete_run(run_id: str) -> bool:
    """
    Remove a run from runs.json.
    Returns True if the run was found and deleted, False if not found.
    """
    runs = _load_all()
    new_runs = [r for r in runs if r.get("id") != run_id]
    if len(new_runs) == len(runs):
        return False   # not found
    _save_all(new_runs)
    logger.info(f"Deleted run {run_id}")
    return True


# ── Internal helper ────────────────────────────────────────────────────────────

def _append_log(run: PipelineRun, level: str, stage: str, message: str) -> None:
    run.log_entries.append(asdict(
        LogEntry(timestamp=_now_iso(), level=level, stage=stage, message=message)
    ))
