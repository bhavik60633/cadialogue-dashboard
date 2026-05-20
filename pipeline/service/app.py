"""
CADialogue Pipeline Service — FastAPI sidecar.

Binds to 127.0.0.1:8765 only.
All routes require Bearer token auth (PIPELINE_SERVICE_TOKEN env var).
The Next.js /api/py proxy is the only caller.

Start with:
    uvicorn pipeline.service.app:app --host 127.0.0.1 --port 8765 --reload
"""
import asyncio
import json
import os
import time
from pathlib import Path

# Load .env from project root so env vars are available when uvicorn starts directly
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except ImportError:
    pass

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .jobs import job_registry, sse_publisher
from ..state import batch_tracker, run_tracker
from ..utils.logger import get_logger

logger = get_logger("pipeline_service")

app = FastAPI(title="CADialogue Pipeline Service", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SERVICE_TOKEN = os.environ.get("PIPELINE_SERVICE_TOKEN", "")


# ── Auth ───────────────────────────────────────────────────────────────────────


async def verify_token(request: Request) -> None:
    if not SERVICE_TOKEN:
        raise HTTPException(500, "PIPELINE_SERVICE_TOKEN not configured")
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth[7:] != SERVICE_TOKEN:
        raise HTTPException(401, "Unauthorized")


Auth = Depends(verify_token)


# ── Health ─────────────────────────────────────────────────────────────────────


@app.get("/health")
async def health(_: None = Auth) -> dict:
    job_registry.cleanup_done()
    return {"status": "ok", "service": "cadialogue-pipeline", "version": "0.2.0"}


# ── SSE events ─────────────────────────────────────────────────────────────────


@app.get("/events/{run_id}")
async def events(run_id: str, _: None = Auth) -> StreamingResponse:
    async def stream():
        queue: asyncio.Queue = asyncio.Queue()
        sse_publisher.subscribe(run_id, queue)
        try:
            yield f"data: {json.dumps({'type':'connected','run_id':run_id})}\n\n"
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=25.0)
                    if data is None:
                        yield f"data: {json.dumps({'type':'done'})}\n\n"
                        break
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            sse_publisher.unsubscribe(run_id, queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Batch endpoints ────────────────────────────────────────────────────────────


@app.post("/batches/today/refresh")
async def refresh_batch(background_tasks: BackgroundTasks, _: None = Auth) -> dict:
    """
    Trigger morning topic discovery.
    Runs in the background; returns immediately with the expected batch_id.
    Call GET /batches/today to poll for the result.
    """
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    batch_id = f"batch_{today}"

    if job_registry.is_running(batch_id):
        return {"status": "already_running", "batch_id": batch_id}

    async def _discover():
        import traceback
        try:
            from ..orchestrator.batch_runner import run_morning_batch
            await run_morning_batch(n=10)
            await sse_publisher.publish("batch_refresh", {"type": "done", "batch_id": batch_id})
        except Exception as exc:
            tb = traceback.format_exc()
            logger.error(f"Batch discovery FAILED:\n{tb}")
            # Persist error so /batches/today/last-error can surface it
            try:
                from pathlib import Path
                Path(__file__).resolve().parent.parent.parent.joinpath(
                    "pipeline", "state", "batch_last_error.txt"
                ).write_text(tb, encoding="utf-8")
            except Exception:
                pass
            from ..state import batch_tracker as bt
            try:
                bt.create_batch([])
            except Exception:
                pass
            await sse_publisher.publish("batch_refresh", {
                "type": "error",
                "message": str(exc),
            })

    task = asyncio.create_task(_discover())
    job_registry.register(batch_id, task, batch_id)

    return {"status": "started", "batch_id": batch_id}


@app.get("/batches/today/last-error")
async def batch_last_error(_: None = Auth) -> dict:
    """Return the last batch discovery error for debugging."""
    from pathlib import Path
    err_file = Path(__file__).resolve().parent.parent.parent / "pipeline" / "state" / "batch_last_error.txt"
    if err_file.exists():
        return {"error": err_file.read_text(encoding="utf-8")}
    return {"error": None}


@app.get("/batches/today")
async def get_today(_: None = Auth) -> dict:
    """Return today's batch + all its topic runs."""
    batch = batch_tracker.get_today_batch()
    if not batch:
        return {"batch": None, "runs": []}

    runs = []
    for run_id in batch.get("topic_run_ids", []):
        run = run_tracker.load_run(run_id)
        if run:
            runs.append(_safe_run(run))

    return {"batch": batch, "runs": runs}


@app.get("/batches/today/events")
async def batch_events(_: None = Auth) -> StreamingResponse:
    """SSE stream for batch-level events (discovery progress)."""
    return await events("batch_refresh", _)  # type: ignore


# ── Run endpoints ──────────────────────────────────────────────────────────────


@app.get("/runs/{run_id}")
async def get_run(run_id: str, _: None = Auth) -> dict:
    run = run_tracker.load_run(run_id)
    if not run:
        raise HTTPException(404, f"Run {run_id} not found")
    return _safe_run(run)


@app.post("/runs/{run_id}/approve")
async def approve_run(run_id: str, _: None = Auth) -> dict:
    run = run_tracker.load_run(run_id)
    if not run:
        raise HTTPException(404, f"Run {run_id} not found")
    allowed = ("pending", "rejected", "failed")
    if run.get("topic_status") not in allowed:
        raise HTTPException(400, f"Can only approve/retry pending, rejected, or failed topics (current: {run.get('topic_status')})")
    # Reset error + status so generation can start fresh
    run_tracker.update_run(run_id, approval_status="approved", error=None)
    run_tracker.update_topic_status(run_id, "approved")
    return {"status": "approved", "run_id": run_id}


@app.post("/runs/{run_id}/reject")
async def reject_run(run_id: str, _: None = Auth) -> dict:
    run = run_tracker.load_run(run_id)
    if not run:
        raise HTTPException(404, f"Run {run_id} not found")
    run_tracker.update_topic_status(run_id, "rejected")
    run_tracker.update_run(run_id, approval_status="rejected")
    return {"status": "rejected", "run_id": run_id}


@app.post("/runs/{run_id}/generate")
async def generate_run(run_id: str, _: None = Auth) -> dict:
    """Start article generation for an approved topic."""
    run = run_tracker.load_run(run_id)
    if not run:
        raise HTTPException(404, f"Run {run_id} not found")
    if run.get("topic_status") != "approved":
        raise HTTPException(400, f"Topic must be approved first (current: {run.get('topic_status')})")
    if job_registry.is_running(run_id):
        return {"status": "already_running", "run_id": run_id}

    from ..orchestrator.topic_runner import run_topic
    task = asyncio.create_task(run_topic(run_id))
    job_registry.register(run_id, task, run_id)

    return {"status": "started", "run_id": run_id}


# ── Article review gate (human-in-the-loop publish approval) ──────────────────


@app.post("/runs/{run_id}/approve-for-publish")
async def approve_for_publish(run_id: str, _: None = Auth) -> dict:
    """
    Flip the WordPress draft to PUBLIC after a human has read & approved it.

    Required state: topic_status must be `pending_review` and run must have
    a `wp_post_id` (the draft created during generation).

    Side effects after success:
      • WP post status: draft → publish
      • topic_status: pending_review → published
      • Triggers SEO post-publish pipeline (embeddings, internal linking,
        Google Indexing API + IndexNow ping) via wordpress_client.
    """
    run = run_tracker.load_run(run_id)
    if not run:
        raise HTTPException(404, f"Run {run_id} not found")

    current = run.get("topic_status")
    if current != "pending_review":
        raise HTTPException(
            400,
            f"Article must be in pending_review (current: {current}). "
            "Generate the article first."
        )

    post_id = run.get("wp_post_id")
    if not post_id:
        raise HTTPException(400, "No WordPress draft exists for this run.")

    from ..config import load_config
    from ..publisher.wordpress_client import transition_draft_to_publish
    cfg = load_config()

    try:
        run_tracker.update_topic_status(run_id, "publishing")
        run_tracker.log(run_id, "info", "publish",
                        f"User approved draft #{post_id}. Promoting to live…")
        post = await asyncio.to_thread(transition_draft_to_publish, post_id, cfg)
        post_url = post.get("link", "")

        run_tracker.update_run(
            run_id,
            wp_post_url=post_url,
            approval_status="approved",
            approved_by="dashboard",
        )
        run_tracker.complete_run(run_id, post_url)
        run_tracker.update_topic_status(run_id, "published")
        run_tracker.log(run_id, "info", "done",
                        f"LIVE — {post_url}")

        return {
            "status":      "published",
            "run_id":      run_id,
            "wp_post_id":  post_id,
            "wp_post_url": post_url,
        }
    except Exception as exc:
        run_tracker.log(run_id, "error", "publish_approval", str(exc))
        run_tracker.update_topic_status(run_id, "pending_review")
        raise HTTPException(500, f"Approval failed: {exc}")


@app.post("/runs/{run_id}/reject-article")
async def reject_article(run_id: str, _: None = Auth) -> dict:
    """
    Reject an article that's pending_review. Marks the run as rejected and
    leaves the WordPress draft in place (so the user can delete it from
    wp-admin or recover the text). Does NOT auto-delete the draft to give
    the user a chance to copy useful material.
    """
    run = run_tracker.load_run(run_id)
    if not run:
        raise HTTPException(404, f"Run {run_id} not found")

    current = run.get("topic_status")
    if current not in ("pending_review", "article_ready", "saving_draft"):
        raise HTTPException(
            400,
            f"Can only reject pending/ready articles (current: {current})"
        )

    run_tracker.update_topic_status(run_id, "rejected")
    run_tracker.update_run(run_id,
                           approval_status="rejected",
                           rejected_by="dashboard")
    run_tracker.log(run_id, "info", "rejected",
                    "Article rejected by reviewer. WP draft retained for manual cleanup.")

    return {
        "status":     "rejected",
        "run_id":     run_id,
        "wp_post_id": run.get("wp_post_id"),
        "wp_admin_url": run.get("wp_admin_url"),
    }


@app.get("/runs/pending-review")
async def list_pending_review(_: None = Auth) -> dict:
    """List every run currently waiting for human approval to go live."""
    runs = run_tracker.load_all_runs()
    pending = [r for r in runs if r.get("topic_status") == "pending_review"]
    # newest first
    pending.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return {
        "count": len(pending),
        "runs":  [_safe_run(r) for r in pending],
    }


# ── Article + image routes ─────────────────────────────────────────────────────


@app.get("/runs/{run_id}/article")
async def get_article(run_id: str, _: None = Auth) -> dict:
    """Return the run including the full article markdown (_article_draft)."""
    run = run_tracker.load_run(run_id)
    if not run:
        raise HTTPException(404, f"Run {run_id} not found")
    if not run.get("_article_draft"):
        raise HTTPException(404, "Article not generated yet")
    return run   # full run, draft included


class SuggestImagesRequest(BaseModel):
    section_text: str
    section_id: str


@app.post("/runs/{run_id}/sections/{section_id}/suggest-images")
async def suggest_images_route(
    run_id: str,
    section_id: str,
    body: SuggestImagesRequest,
    _: None = Auth,
) -> dict:
    """Ask GPT-4o-mini to propose 4-6 image ideas for this article section."""
    run = run_tracker.load_run(run_id)
    if not run:
        raise HTTPException(404, f"Run {run_id} not found")

    from ..config import load_config
    from ..writer.image_suggester import suggest_images

    cfg = load_config()
    topic_title = (run.get("topic_meta") or {}).get("title", run.get("topic", ""))
    ideas = await suggest_images(
        section_text=body.section_text,
        topic_title=topic_title,
        section_id=section_id,
        config=cfg,
    )
    return {"ideas": [i.to_dict() for i in ideas]}


class GenerateImageRequest(BaseModel):
    idea_index: int
    dalle_prompt: str
    alt_text: str = ""


@app.post("/runs/{run_id}/sections/{section_id}/generate-image")
async def generate_image_route(
    run_id: str,
    section_id: str,
    body: GenerateImageRequest,
    _: None = Auth,
) -> dict:
    """
    Generate a DALL-E 3 image in 3 aspect ratios and persist the result
    to the run's `images` list.
    """
    run = run_tracker.load_run(run_id)
    if not run:
        raise HTTPException(404, f"Run {run_id} not found")

    from ..config import load_config
    from ..writer.image_generator import generate_image

    cfg = load_config()
    ratios = await generate_image(
        dalle_prompt=body.dalle_prompt,
        run_id=run_id,
        section_id=section_id,
        idea_index=body.idea_index,
        config=cfg,
    )

    # Persist into run.images list
    images: list = run.get("images") or []
    # Remove any previous entry for this section+idea combo
    images = [
        img for img in images
        if not (img.get("section_id") == section_id and img.get("idea_index") == body.idea_index)
    ]
    images.append({
        "section_id": section_id,
        "idea_index": body.idea_index,
        "dalle_prompt": body.dalle_prompt,
        "alt_text": body.alt_text,
        "ratios": ratios,
        "selected_ratio": "16:9",   # default selection
    })
    run_tracker.update_run(run_id, images=images)

    # Advance topic_status to images_ready if article_ready
    if run.get("topic_status") == "article_ready":
        run_tracker.update_topic_status(run_id, "images_ready")

    return {"ratios": ratios, "section_id": section_id}


class SelectRatioRequest(BaseModel):
    section_id: str
    idea_index: int
    ratio: str  # "16:9" | "1:1" | "4:3"


@app.post("/runs/{run_id}/select-ratio")
async def select_ratio_route(
    run_id: str,
    body: SelectRatioRequest,
    _: None = Auth,
) -> dict:
    """Persist the user's chosen aspect ratio for a generated image."""
    run = run_tracker.load_run(run_id)
    if not run:
        raise HTTPException(404, f"Run {run_id} not found")

    images: list = run.get("images") or []
    for img in images:
        if img.get("section_id") == body.section_id and img.get("idea_index") == body.idea_index:
            img["selected_ratio"] = body.ratio
            break

    run_tracker.update_run(run_id, images=images)
    return {"ok": True}


# ── Stock photo routes ─────────────────────────────────────────────────────────


@app.post("/runs/{run_id}/sections/{section_id}/stock-photos")
async def stock_photos_route(
    run_id: str,
    section_id: str,
    body: SuggestImagesRequest,   # reuse: has section_text
    _: None = Auth,
) -> dict:
    """Return real Pexels stock photos relevant to this section."""
    run = run_tracker.load_run(run_id)
    if not run:
        raise HTTPException(404, f"Run {run_id} not found")

    from ..config import load_config
    from ..writer.stock_photo_fetcher import fetch_stock_photos

    cfg = load_config()
    topic_title = (run.get("topic_meta") or {}).get("title", run.get("topic", ""))

    photos = await fetch_stock_photos(
        section_text=body.section_text,
        topic_title=topic_title,
        section_id=section_id,
        config=cfg,
    )
    return {
        "photos": [p.to_dict() for p in photos],
        "has_pexels_key": bool(cfg.pexels_api_key),
    }


class DownloadStockPhotoRequest(BaseModel):
    pexels_id: int
    thumb_url: str
    full_url: str
    description: str
    photographer: str


@app.post("/runs/{run_id}/sections/{section_id}/use-stock-photo")
async def use_stock_photo_route(
    run_id: str,
    section_id: str,
    body: DownloadStockPhotoRequest,
    _: None = Auth,
) -> dict:
    """Download the chosen Pexels photo, save in 3 ratios, persist to run."""
    run = run_tracker.load_run(run_id)
    if not run:
        raise HTTPException(404, f"Run {run_id} not found")

    from ..config import load_config
    from ..writer.stock_photo_fetcher import StockPhoto, download_stock_photo

    cfg = load_config()
    photo = StockPhoto(
        pexels_id=body.pexels_id,
        description=body.description,
        photographer=body.photographer,
        thumb_url=body.thumb_url,
        full_url=body.full_url,
        width=0, height=0,
    )
    ratios = await download_stock_photo(photo, run_id, section_id, cfg)

    # Persist to run.images
    images: list = run.get("images") or []
    images = [img for img in images if img.get("section_id") != section_id]
    images.append({
        "section_id":    section_id,
        "idea_index":    0,
        "dalle_prompt":  "",
        "alt_text":      body.description,
        "photographer":  body.photographer,
        "pexels_id":     body.pexels_id,
        "ratios":        ratios,
        "selected_ratio":"16:9",
        "source":        "pexels",
    })
    run_tracker.update_run(run_id, images=images)
    if run.get("topic_status") == "article_ready":
        run_tracker.update_topic_status(run_id, "images_ready")

    return {"ratios": ratios, "section_id": section_id}


@app.post("/runs/{run_id}/sections/{section_id}/upload-device-photo")
async def upload_device_photo(
    run_id: str,
    section_id: str,
    file: UploadFile = File(...),
    _: None = Auth,
) -> dict:
    """
    Accept a user-uploaded photo from their device, save it in 3 aspect ratios,
    and persist the result to the run (same shape as use-stock-photo).
    """
    import io
    run = run_tracker.load_run(run_id)
    if not run:
        raise HTTPException(404, f"Run {run_id} not found")

    # Read file bytes
    img_bytes = await file.read()
    if len(img_bytes) == 0:
        raise HTTPException(400, "Empty file uploaded")

    from PIL import Image
    from ..writer.image_generator import _crop_to_ratio, _ensure_dir

    try:
        img_original = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    except Exception as exc:
        raise HTTPException(400, f"Could not open image: {exc}")

    out_dir = _ensure_dir(run_id)
    safe_name = file.filename or "upload"
    # Strip extension, sanitise
    stem_raw = safe_name.rsplit(".", 1)[0][:40]
    stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem_raw)
    stem = f"{section_id}_device_{stem}"

    ratios = {
        "16:9": (
            img_original if abs(img_original.width / max(img_original.height, 1) - 16/9) < 0.4
            else _crop_to_ratio(img_original, 16, 9),
            f"{stem}_16x9.png",
        ),
        "1:1":  (_crop_to_ratio(img_original, 1, 1),  f"{stem}_1x1.png"),
        "4:3":  (_crop_to_ratio(img_original, 4, 3),  f"{stem}_4x3.png"),
    }

    saved: dict[str, str] = {}
    for ratio_key, (pil_img, filename) in ratios.items():
        file_path = out_dir / filename
        pil_img.save(file_path, format="PNG", optimize=True)
        saved[ratio_key] = f"/api/images/{run_id}/{filename}"

    # Persist to run.images
    images: list = run.get("images") or []
    images = [img for img in images if img.get("section_id") != section_id]
    images.append({
        "section_id":    section_id,
        "idea_index":    0,
        "dalle_prompt":  "",
        "alt_text":      safe_name,
        "photographer":  "",
        "source":        "device",
        "ratios":        saved,
        "selected_ratio":"16:9",
    })
    run_tracker.update_run(run_id, images=images)
    if run.get("topic_status") == "article_ready":
        run_tracker.update_topic_status(run_id, "images_ready")

    return {"ratios": saved, "section_id": section_id, "source": "device"}


class SaveArticleRequest(BaseModel):
    article: str   # updated markdown from the editor


@app.patch("/runs/{run_id}/article")
async def save_article(run_id: str, body: SaveArticleRequest, _: None = Auth) -> dict:
    """Persist edited article markdown back to the run."""
    run = run_tracker.load_run(run_id)
    if not run:
        raise HTTPException(404, f"Run {run_id} not found")
    run_tracker.update_run(run_id, _article_draft=body.article)
    return {"ok": True, "length": len(body.article)}


class PublishWithImagesRequest(BaseModel):
    article: str = ""              # optional override — if empty, uses stored draft
    images_override: list = []     # if non-empty, use this instead of run["images"]


@app.post("/runs/{run_id}/publish-with-images")
async def publish_with_images_route(
    run_id: str,
    body: PublishWithImagesRequest,
    background_tasks: BackgroundTasks,
    _: None = Auth,
) -> dict:
    """
    Upload all selected images to WordPress, embed them in the article,
    then update the existing WordPress post.
    """
    run = run_tracker.load_run(run_id)
    if not run:
        raise HTTPException(404, f"Run {run_id} not found")

    wp_post_id = run.get("wp_post_id")
    if not wp_post_id:
        raise HTTPException(400, "This run has no WordPress post yet — publish the article first")

    article = body.article or run.get("_article_draft", "")
    if not article:
        raise HTTPException(400, "No article content available")

    # images_override from frontend takes precedence (carries isFeatured flags)
    images = body.images_override if body.images_override else (run.get("images") or [])

    async def _do_publish():
        import traceback
        try:
            from ..config import load_config
            from ..publisher.wordpress_client import update_post_with_images
            from pipeline.state.image_store import IMAGES_DIR

            cfg = load_config()
            run_tracker.update_topic_status(run_id, "publishing")

            post = await update_post_with_images(
                wp_post_id=wp_post_id,
                article_markdown=article,
                images=images,
                config=cfg,
                images_dir=IMAGES_DIR / run_id,
            )
            run_tracker.update_run(run_id, topic_status="published", wp_post_url=post.get("link", ""))
            await sse_publisher.publish(run_id, {"type": "published", "url": post.get("link", "")})

            # ── SEO pipeline on final content (images embedded) ──────────────
            # Re-run AFTER images are embedded so the linker sees the full HTML.
            # _run_seo_post_publish is fire-and-forget (background thread).
            try:
                from ..publisher.wordpress_client import _run_seo_post_publish
                _run_seo_post_publish(post, cfg)
            except Exception as seo_exc:
                logger.warning(f"SEO post-publish hook failed for run {run_id}: {seo_exc}")

        except Exception as exc:
            tb = traceback.format_exc()
            run_tracker.update_run(run_id, topic_status="failed", error=str(exc))
            await sse_publisher.publish(run_id, {"type": "error", "message": str(exc)})

    task = asyncio.create_task(_do_publish())
    job_registry.register(run_id + "_publish", task, run_id)
    return {"status": "publishing", "run_id": run_id}


# ── Topic Library routes ───────────────────────────────────────────────────────


@app.get("/library/topics")
async def library_list(
    category: str = "",
    q: str = "",
    _: None = Auth,
) -> dict:
    """List topics from the library, optionally filtered by category or search query."""
    from ..library.topic_library import list_topics, category_counts, CATEGORIES
    topics = list_topics(category=category or None, query=q or None)
    counts = category_counts()
    return {
        "topics": topics,
        "counts": counts,
        "categories": [
            {"key": k, "display": v["display"], "emoji": v["emoji"], "count": counts.get(k, 0)}
            for k, v in CATEGORIES.items()
        ],
    }


class AddTopicRequest(BaseModel):
    title: str
    summary: str = ""
    category: str = "markets"
    added_by: str = "dashboard"
    sources: list[dict] = []


@app.post("/library/topics")
async def library_add(body: AddTopicRequest, _: None = Auth) -> dict:
    """Manually add a topic to the library."""
    from ..library.topic_library import add_topic
    topic = add_topic(
        title=body.title,
        summary=body.summary,
        category=body.category,
        added_by=body.added_by,
        sources=body.sources,
    )
    return {"topic": topic}


@app.delete("/library/topics/{topic_id}")
async def library_delete(topic_id: str, _: None = Auth) -> dict:
    """Delete a topic from the library."""
    from ..library.topic_library import delete_topic
    ok = delete_topic(topic_id)
    if not ok:
        raise HTTPException(404, f"Topic {topic_id} not found")
    return {"deleted": True}


class PromoteTopicRequest(BaseModel):
    added_by: str = "dashboard"


@app.post("/library/topics/{topic_id}/promote")
async def library_promote(
    topic_id: str,
    body: PromoteTopicRequest,
    _: None = Auth,
) -> dict:
    """
    Promote a library topic to today's queue:
    Creates a TopicRun in pending state and marks the library entry promoted.
    """
    from datetime import datetime, timezone
    from ..library.topic_library import get_topic, promote_topic_to_queue
    from ..state import run_tracker, batch_tracker

    topic = get_topic(topic_id)
    if not topic:
        raise HTTPException(404, f"Library topic {topic_id} not found")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    batch_id = f"batch_{today}"

    # Ensure today's batch exists
    batch = batch_tracker.get_today_batch()
    if not batch:
        batch = batch_tracker.create_batch([])

    # Determine next available run_index to avoid ID collisions
    run_index = batch_tracker.get_next_run_index(batch_id)

    # Create a new TopicRun in pending state
    run_id = run_tracker.init_topic_run(
        batch_id=batch_id,
        topic_meta={
            "title":    topic["title"],
            "summary":  topic.get("summary", ""),
            "category": topic.get("category", "markets"),
            "sources":  topic.get("sources", []),
            "score":    topic.get("score", 0.0),
            "added_by": body.added_by,
        },
        run_index=run_index,
    )

    # Add run to batch
    batch_tracker.add_run_to_batch(batch_id, run_id)

    # Mark topic as promoted
    promote_topic_to_queue(topic_id, batch_id)

    return {"run_id": run_id, "batch_id": batch_id, "topic": topic}


# ── WordPress Post Manager routes ──────────────────────────────────────────────


class WpPostData(BaseModel):
    title: str | None = None
    content: str | None = None          # HTML
    status: str | None = None           # "publish" | "draft" | "private"
    slug: str | None = None
    excerpt: str | None = None
    categories: list[int] | None = None
    featured_media: int | None = None   # 0 = remove featured image


@app.get("/wp/posts")
async def wp_list_posts(
    page: int = 1,
    per_page: int = 20,
    status: str = "any",
    search: str = "",
    _: None = Auth,
) -> dict:
    """List WordPress posts with pagination."""
    import asyncio
    from ..config import load_config
    from ..publisher.wp_manager import list_posts

    cfg = load_config()
    posts, total, total_pages = await asyncio.to_thread(
        list_posts, cfg, page, per_page, status, search
    )
    return {"posts": posts, "total": total, "total_pages": total_pages, "page": page}


@app.get("/wp/posts/{post_id}")
async def wp_get_post(post_id: int, _: None = Auth) -> dict:
    """Get a single WordPress post by ID."""
    import asyncio
    from ..config import load_config
    from ..publisher.wp_manager import get_post

    cfg = load_config()
    return await asyncio.to_thread(get_post, cfg, post_id)


@app.post("/wp/posts")
async def wp_create_post(body: WpPostData, _: None = Auth) -> dict:
    """
    Create a new WordPress post from the dashboard Posts section.
    After publish, automatically triggers the full SEO pipeline:
      - Embeds article for semantic search
      - Injects 30+ internal links
      - Submits URL to Google + IndexNow
    """
    import asyncio
    from ..config import load_config
    from ..publisher.wp_manager import create_post

    cfg  = load_config()
    data = body.model_dump(exclude_none=True)
    if not data.get("title"):
        raise HTTPException(400, "title is required")
    if not data.get("content"):
        raise HTTPException(400, "content is required")

    post = await asyncio.to_thread(create_post, cfg, data)

    # ── Auto SEO: only fire for published posts, not drafts ──────────────────
    if post.get("status") == "publish":
        from ..publisher.wordpress_client import _run_seo_post_publish
        _run_seo_post_publish(post, cfg)   # runs in background thread

    return post


@app.put("/wp/posts/{post_id}")
async def wp_update_post(post_id: int, body: WpPostData, _: None = Auth) -> dict:
    """Update an existing WordPress post."""
    import asyncio
    from ..config import load_config
    from ..publisher.wp_manager import update_post

    cfg = load_config()
    data = body.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(400, "No fields provided to update")
    return await asyncio.to_thread(update_post, cfg, post_id, data)


@app.delete("/wp/posts/{post_id}")
async def wp_delete_post(post_id: int, force: bool = False, _: None = Auth) -> dict:
    """Trash (or permanently delete) a WordPress post."""
    import asyncio
    from ..config import load_config
    from ..publisher.wp_manager import delete_post

    cfg = load_config()
    return await asyncio.to_thread(delete_post, cfg, post_id, force)


@app.post("/wp/media")
async def wp_upload_media(
    file: UploadFile = File(...),
    alt_text: str = "",
    title: str = "",
    _: None = Auth,
) -> dict:
    """Upload an image to the WordPress media library."""
    import asyncio
    from ..config import load_config
    from ..publisher.wp_manager import upload_media

    img_bytes = await file.read()
    if not img_bytes:
        raise HTTPException(400, "Empty file uploaded")

    cfg = load_config()
    mime = file.content_type or "image/jpeg"
    fname = file.filename or "upload.jpg"
    return await asyncio.to_thread(upload_media, cfg, img_bytes, fname, mime, alt_text, title)


@app.get("/usage/stats")
async def usage_stats(_: None = Auth) -> dict:
    """
    Returns estimated OpenAI spend for the current month based on run history,
    plus whether any AI job is currently running.

    Cost model (conservative estimates):
      Article generation (write + humanise): $0.09 (gpt-4o, ~5 000 tokens)
      SEO meta + topic scoring per batch:    $0.002 (gpt-4o-mini, ~10 000 tokens)
      AI image (gpt-image-1 / dall-e-3):     $0.06 per image
      Pexels query generation:               ~$0 (gpt-4o-mini, <100 tokens)
    """
    import os
    from datetime import datetime, timezone
    from ..state import run_tracker

    USD_PER_INR = 83.5          # approximate exchange rate
    COST_ARTICLE_USD  = 0.09    # write + humanise
    COST_BATCH_USD    = 0.002   # topic discovery + scoring per batch
    COST_IMAGE_USD    = 0.06    # per generated AI image
    MONTHLY_CAP_USD   = float(os.environ.get("OPENAI_MONTHLY_USD_CAP", "60"))

    today = datetime.now(timezone.utc)
    month_prefix = today.strftime("%Y-%m")   # e.g. "2026-05"

    all_runs = run_tracker.load_all_runs()

    article_count = 0
    image_count   = 0
    batch_count_set: set = set()

    for run in all_runs:
        started = run.get("started_at", "")
        if not started.startswith(month_prefix):
            continue

        status = run.get("topic_status") or run.get("status") or ""
        if status in ("article_ready", "images_ready", "publishing", "published", "completed"):
            article_count += 1
            batch_id = run.get("batch_id")
            if batch_id:
                batch_count_set.add(batch_id)

        images = run.get("images") or []
        for img in images:
            # Only count AI-generated images (not Pexels/device)
            if img.get("source") not in ("pexels", "device") and img.get("ratios"):
                image_count += 1

    estimated_usd = (
        article_count * COST_ARTICLE_USD
        + len(batch_count_set) * COST_BATCH_USD
        + image_count * COST_IMAGE_USD
    )
    estimated_inr = estimated_usd * USD_PER_INR

    # Is any AI job currently running?
    active_statuses = {"generating", "publishing"}
    is_active = any(
        run.get("topic_status") in active_statuses
        for run in all_runs
    ) or any(
        job_registry.is_running(jid)
        for jid in list(job_registry._jobs.keys())  # type: ignore[attr-defined]
    )

    return {
        "month": month_prefix,
        "article_count": article_count,
        "image_count": image_count,
        "batch_count": len(batch_count_set),
        "estimated_usd": round(estimated_usd, 3),
        "estimated_inr": round(estimated_inr, 1),
        "monthly_cap_usd": MONTHLY_CAP_USD,
        "monthly_cap_inr": round(MONTHLY_CAP_USD * USD_PER_INR, 0),
        "pct_used": round((estimated_usd / MONTHLY_CAP_USD) * 100, 1) if MONTHLY_CAP_USD else 0,
        "is_active": is_active,
    }


@app.get("/wp/search-photos")
async def wp_search_photos(
    q: str = "",
    per_page: int = 12,
    _: None = Auth,
) -> dict:
    """
    Search Pexels for stock photos matching a keyword query.
    Returns up to per_page photo objects with thumb_url and full_url.
    """
    if not q.strip():
        raise HTTPException(400, "q (search query) is required")

    from ..config import load_config
    from ..writer.stock_photo_fetcher import _pexels_search

    cfg = load_config()
    if not cfg.pexels_api_key:
        raise HTTPException(503, "PEXELS_API_KEY is not configured on this server")

    import asyncio
    photos = await asyncio.to_thread(
        _pexels_search, q.strip(), cfg.pexels_api_key, min(per_page, 24)
    )
    return {"photos": [p.to_dict() for p in photos], "query": q}


class UsePexelsPhotoRequest(BaseModel):
    full_url: str
    description: str = ""
    photographer: str = ""


@app.post("/wp/use-pexels-photo")
async def wp_use_pexels_photo(body: UsePexelsPhotoRequest, _: None = Auth) -> dict:
    """
    Download a Pexels photo by URL and upload it directly to the
    WordPress media library. Returns the WP media object (id, source_url).
    """
    import asyncio
    import requests as rq

    from ..config import load_config
    from ..publisher.wp_manager import upload_media

    if not body.full_url:
        raise HTTPException(400, "full_url is required")

    cfg = load_config()

    # Download the Pexels image
    try:
        img_bytes = await asyncio.to_thread(
            lambda: rq.get(body.full_url, timeout=30).content
        )
    except Exception as exc:
        raise HTTPException(502, f"Failed to download photo: {exc}")

    # Derive a filename from the URL
    filename = body.full_url.split("?")[0].split("/")[-1] or "pexels-photo.jpg"
    if "." not in filename:
        filename += ".jpg"

    mime = "image/jpeg" if filename.lower().endswith((".jpg", ".jpeg")) else "image/png"
    alt  = body.description or f"Photo by {body.photographer}"
    title = body.description or filename

    media = await asyncio.to_thread(upload_media, cfg, img_bytes, filename, mime, alt, title)
    return {"id": media["id"], "source_url": media["source_url"], "alt": alt}


@app.get("/wp/categories")
async def wp_get_categories(_: None = Auth) -> dict:
    """List all WordPress categories."""
    import asyncio
    from ..config import load_config
    from ..publisher.wp_manager import get_categories

    cfg = load_config()
    cats = await asyncio.to_thread(get_categories, cfg)
    return {"categories": cats}


# ═══════════════════════════════════════════════════════════════════════════════
# SEO ENGINE ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

# In-memory store for programmatic gen errors (cleared after first poll read)
_prog_errors: dict[str, str] = {}

# In-memory store for article-repair job results (one slot — only one repair at a time)
_repair_result: dict = {"state": "idle"}  # state: idle | running | done | error


# ── SEO: Embeddings ────────────────────────────────────────────────────────────

@app.post("/seo/embeddings/rebuild")
async def seo_rebuild_embeddings(background_tasks: BackgroundTasks, _: None = Auth) -> dict:
    """
    Rebuild OpenAI embeddings for ALL published WordPress posts.
    Runs in a THREAD POOL so the event loop is never blocked.
    """
    async def _do_rebuild():
        try:
            from ..config import load_config
            from ..publisher.wp_manager import list_posts
            from ..seo.embeddings_store import rebuild_all_embeddings

            cfg             = load_config()
            # Both WP fetch and embedding loop run in thread pool (blocking I/O)
            posts, total, _ = await asyncio.to_thread(list_posts, cfg, 1, 100, "publish")
            logger.info(f"[embed_rebuild] fetched {len(posts)} posts from WP")
            count           = await asyncio.to_thread(rebuild_all_embeddings, cfg, posts)
            logger.info(f"[embed_rebuild] done — {count} embeddings built")
            await sse_publisher.publish("seo_rebuild", {"type": "done", "count": count})
        except Exception as exc:
            logger.exception(f"[embed_rebuild] FAILED: {exc}")
            await sse_publisher.publish("seo_rebuild", {"type": "error", "message": str(exc)})

    task = asyncio.create_task(_do_rebuild())
    job_registry.register("seo_embed_rebuild", task, "seo_embed_rebuild")
    return {"status": "started", "message": "Rebuilding embeddings in background"}


@app.get("/seo/embeddings/status")
async def seo_embedding_status(_: None = Auth) -> dict:
    """Return count of embedded articles and last update time."""
    from ..seo.embeddings_store import load_embeddings
    data = load_embeddings()
    if not data:
        return {"count": 0, "last_updated": None}
    last = max(v.get("updated_at", 0) for v in data.values())
    return {"count": len(data), "last_updated": last}


# ── SEO: Internal Linking ──────────────────────────────────────────────────────

class LinkArticleRequest(BaseModel):
    post_id: int
    post_title: str
    post_url: str
    post_html: str = ""   # optional: if empty, fetched from WP


@app.post("/seo/link/article")
async def seo_link_article(body: LinkArticleRequest, _: None = Auth) -> dict:
    """
    Run the full internal linking pass for a single article:
      - Inject 30+ outgoing links into the article
      - Update 5-8 existing articles to link back
      - Return stats (outgoing_count, backlinks_added)
    """
    import asyncio
    from ..config import load_config
    from ..publisher.wp_manager import get_post, update_post
    from ..seo.internal_linker import link_article

    cfg = load_config()

    # Fetch HTML if not provided
    html = body.post_html
    if not html:
        post = await asyncio.to_thread(get_post, cfg, body.post_id)
        html = post.get("content", {}).get("rendered", "")

    def _update(pid: int, content: str):
        asyncio.get_event_loop().run_until_complete(
            asyncio.to_thread(update_post, cfg, pid, {"content": content})
        )

    def _get_post(pid: int) -> dict:
        import asyncio as aio
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(get_post, cfg, pid).result()

    stats = link_article(
        new_post_id=body.post_id,
        new_post_html=html,
        new_post_title=body.post_title,
        new_post_url=body.post_url,
        config=cfg,
        update_post_fn=lambda pid, content: update_post(cfg, pid, {"content": content}),
        get_post_fn=lambda pid: get_post(cfg, pid),
    )
    return stats


@app.get("/seo/link/stats")
async def seo_link_stats(_: None = Auth) -> dict:
    """Return link graph stats: total links, orphan pages, averages."""
    from ..seo.internal_linker import get_link_stats
    return get_link_stats()


@app.get("/seo/link/orphans")
async def seo_orphan_pages(_: None = Auth) -> dict:
    """
    Return list of published posts with zero incoming internal links.
    These are 'orphan pages' — invisible to Google's link graph.
    """
    import asyncio
    from ..config import load_config
    from ..publisher.wp_manager import list_posts
    from ..seo.internal_linker import find_orphan_posts

    cfg         = load_config()
    posts, _, _ = await asyncio.to_thread(list_posts, cfg, 1, 100, "publish")
    post_ids    = [p["id"] for p in posts]
    orphan_ids  = find_orphan_posts(post_ids)

    # Enrich with titles
    id_to_title = {p["id"]: p.get("title", {}).get("rendered", "") for p in posts}
    orphans = [{"post_id": pid, "title": id_to_title.get(pid, "")} for pid in orphan_ids]
    return {"orphans": orphans, "count": len(orphans)}


# ── SEO: Keyword Engine ────────────────────────────────────────────────────────

class KeywordDiscoveryRequest(BaseModel):
    extra_seeds: list[str] = []


@app.post("/seo/keywords/discover")
async def seo_discover_keywords(
    body: KeywordDiscoveryRequest,
    background_tasks: BackgroundTasks,
    _: None = Auth,
) -> dict:
    """
    Run full keyword discovery + clustering pipeline.
    Expands seeds via Google Autocomplete + DDG, clusters by embedding similarity.
    Runs in background (~2-3 min for full discovery).
    """
    async def _do_discover():
        from ..config import load_config
        from ..seo.keyword_engine import run_keyword_discovery
        cfg    = load_config()
        # run_keyword_discovery does many HTTP calls — must be in thread
        result = await asyncio.to_thread(run_keyword_discovery, cfg, body.extra_seeds or [])
        await sse_publisher.publish("seo_kw", {"type": "done", **result})

    task = asyncio.create_task(_do_discover())
    job_registry.register("seo_kw_discover", task, "seo_kw_discover")
    return {"status": "started"}


@app.get("/seo/keywords/clusters")
async def seo_keyword_clusters(_: None = Auth) -> dict:
    """Return all keyword clusters from the database."""
    from ..seo.keyword_engine import load_kw_store
    store = load_kw_store()
    # Truncate embeddings before sending (too large)
    clusters = []
    for c in store.get("clusters", []):
        clusters.append({k: v for k, v in c.items() if k != "embedding"})
    return {
        "clusters": clusters,
        "total_keywords": sum(len(c.get("keywords", [])) for c in clusters),
        "last_discovery": store.get("last_discovery", 0),
    }


@app.get("/seo/keywords/easy-wins")
async def seo_easy_win_keywords(max_difficulty: int = 40, top_n: int = 20, _: None = Auth) -> dict:
    """
    Return top easy-win keywords: low competition, informational intent.
    Use these to plan your next batch of articles.
    """
    from ..seo.keyword_engine import get_easy_win_keywords
    return {"keywords": get_easy_win_keywords(max_difficulty, top_n)}


# ── SEO: Topic Authority ───────────────────────────────────────────────────────

@app.post("/seo/topics/rebuild")
async def seo_rebuild_topics(background_tasks: BackgroundTasks, _: None = Auth) -> dict:
    """
    Rebuild the full topical authority map from all published posts.
    Assigns each article to a pillar, generates content roadmaps for gaps.
    Slow (~2-3 min) — run once daily or on demand.
    """
    async def _do_rebuild():
        try:
            from ..config import load_config
            from ..publisher.wp_manager import list_posts
            from ..seo.topic_authority import rebuild_topic_map
            cfg    = load_config()
            posts, _, _ = await asyncio.to_thread(list_posts, cfg, 1, 100, "publish")
            logger.info(f"[topic_rebuild] fetched {len(posts)} posts from WP")
            # rebuild_topic_map makes many OpenAI calls — MUST run in thread pool
            result = await asyncio.to_thread(rebuild_topic_map, cfg, posts)
            logger.info(f"[topic_rebuild] done — authority_score={result.get('authority_score')}")
            await sse_publisher.publish("seo_topics", {
                "type": "done",
                "authority_score": result.get("authority_score"),
                "pillars": len(result.get("pillars", [])),
            })
        except Exception as exc:
            logger.exception(f"[topic_rebuild] FAILED: {exc}")
            await sse_publisher.publish("seo_topics", {"type": "error", "message": str(exc)})

    task = asyncio.create_task(_do_rebuild())
    job_registry.register("seo_topic_rebuild", task, "seo_topic_rebuild")
    return {"status": "started"}


@app.get("/seo/topics/map")
async def seo_topic_map(_: None = Auth) -> dict:
    """Return the current topic authority map."""
    from ..seo.topic_authority import load_topic_map
    return load_topic_map()


@app.get("/seo/topics/coverage")
async def seo_coverage_report(_: None = Auth) -> dict:
    """Return a concise topical coverage summary for the SEO dashboard."""
    from ..seo.topic_authority import get_coverage_report
    return get_coverage_report()


@app.get("/seo/topics/roadmap")
async def seo_roadmap(priority: str = "any", top_n: int = 20, _: None = Auth) -> dict:
    """
    Return the top content roadmap items — articles to write next.
    Sorted by priority: high → medium → low.
    Use these to fill topical authority gaps.
    """
    from ..seo.topic_authority import get_top_roadmap_items
    items = get_top_roadmap_items(priority, top_n)
    return {"items": items, "count": len(items)}


# ── SEO: Scoring ──────────────────────────────────────────────────────────────

@app.get("/seo/scores")
async def seo_all_scores(_: None = Auth) -> dict:
    """Return SEO scores for all published posts (from cache)."""
    from ..seo.seo_scorer import load_scores
    scores = load_scores()
    items  = list(scores.values())
    items.sort(key=lambda x: x.get("total_score", 0), reverse=True)
    avg = round(sum(i.get("total_score", 0) for i in items) / max(len(items), 1), 1)
    return {"scores": items, "average": avg, "count": len(items)}


@app.post("/seo/scores/rebuild")
async def seo_rebuild_scores(background_tasks: BackgroundTasks, _: None = Auth) -> dict:
    """Re-score all published posts. Runs in background."""
    async def _do_score():
        try:
            from ..config import load_config
            from ..publisher.wp_manager import list_posts
            from ..seo.seo_scorer import score_all_articles
            cfg    = load_config()
            posts, _, _ = await asyncio.to_thread(list_posts, cfg, 1, 100, "publish")
            logger.info(f"[score_rebuild] scoring {len(posts)} posts")
            result = await asyncio.to_thread(score_all_articles, posts)
            logger.info(f"[score_rebuild] done — avg {result.get('average_score')}")
            await sse_publisher.publish("seo_scores", {"type": "done", **result})
        except Exception as exc:
            logger.exception(f"[score_rebuild] FAILED: {exc}")
            await sse_publisher.publish("seo_scores", {"type": "error", "message": str(exc)})

    task = asyncio.create_task(_do_score())
    job_registry.register("seo_score_rebuild", task, "seo_score_rebuild")
    return {"status": "started"}


@app.get("/seo/scores/{post_id}")
async def seo_score_post(post_id: int, _: None = Auth) -> dict:
    """Get or compute the SEO score for a single post."""
    import asyncio
    from ..config import load_config
    from ..publisher.wp_manager import get_post
    from ..seo.seo_scorer import load_scores, score_article

    scores = load_scores()
    cached = scores.get(str(post_id))
    # Return cached if less than 1 hour old
    if cached and (time.time() - cached.get("scored_at", 0)) < 3600:
        return cached

    cfg  = load_config()
    post = await asyncio.to_thread(get_post, cfg, post_id)
    return score_article(post)


# ── SEO: Content Freshness ─────────────────────────────────────────────────────

@app.post("/seo/freshness/scan")
async def seo_freshness_scan(background_tasks: BackgroundTasks, _: None = Auth) -> dict:
    """Scan all posts for stale content and return a freshness report."""
    import asyncio
    from ..config import load_config
    from ..publisher.wp_manager import list_posts
    from ..seo.content_freshness import scan_stale_articles

    cfg    = load_config()
    posts, _, _ = await asyncio.to_thread(list_posts, cfg, 1, 100, "publish")
    result = scan_stale_articles(posts)
    return result


@app.get("/seo/freshness/report")
async def seo_freshness_report(_: None = Auth) -> dict:
    """Return cached freshness stats for the SEO dashboard."""
    from ..seo.content_freshness import get_freshness_report
    return get_freshness_report()


@app.get("/seo/freshness/{post_id}/suggest-updates")
async def seo_suggest_updates(post_id: int, _: None = Auth) -> dict:
    """
    Use GPT-4o to analyse a stale article and suggest specific update actions.
    Returns a structured update plan with outdated sections, new data needed, etc.
    """
    import asyncio
    from ..config import load_config
    from ..publisher.wp_manager import get_post
    from ..seo.content_freshness import suggest_updates_for_article

    cfg  = load_config()
    post = await asyncio.to_thread(get_post, cfg, post_id)
    return suggest_updates_for_article(post, cfg)


# ── SEO: Programmatic SEO ──────────────────────────────────────────────────────

@app.get("/seo/programmatic/queue")
async def seo_prog_queue(_: None = Auth) -> dict:
    """Return list of pre-defined programmatic pages not yet generated."""
    from ..seo.programmatic_seo import get_generation_queue
    return {"queue": get_generation_queue()}


class ProgrammaticGenerateRequest(BaseModel):
    template_type: str   # "best_for" | "guide_for" | "vs_comparison" | "how_to" | "year_report"
    params: dict         # template-specific params


@app.post("/seo/programmatic/generate")
async def seo_prog_generate(body: ProgrammaticGenerateRequest, _: None = Auth) -> dict:
    """
    Fire-and-forget: starts generation in background and returns the slug immediately.
    GPT-4o takes 40-90s — holding the HTTP connection that long causes Render's
    30-second timeout to kill the request.  Poll GET /seo/programmatic/status/{slug}
    every 3s until status == "done" or "error".
    """
    from ..seo.programmatic_seo import _build_page_meta

    # Compute slug synchronously (fast — no API calls)
    try:
        meta = _build_page_meta(body.template_type, body.params)
        slug = meta["slug"]
    except Exception:
        slug = f"prog_{int(time.time())}"

    async def _do_generate():
        try:
            from ..config import load_config
            from ..seo.programmatic_seo import generate_programmatic_page
            cfg    = load_config()
            result = await asyncio.to_thread(
                generate_programmatic_page, body.template_type, body.params, cfg
            )
            if result.get("error"):
                # generate_programmatic_page returns {"error": "generation_failed"} on empty content
                msg = f"Content generation returned empty — check OpenAI key and model quota"
                logger.error(f"[prog_generate] {msg} for {slug}")
                _prog_errors[slug] = msg
            else:
                logger.info(f"[prog_generate] done — {result.get('title')} ({result.get('word_count')} words)")
        except Exception as exc:
            msg = str(exc)
            logger.exception(f"[prog_generate] FAILED for {slug}: {msg}")
            _prog_errors[slug] = msg

    task = asyncio.create_task(_do_generate())
    job_registry.register(f"prog_{slug}", task, f"prog_{slug}")
    return {"status": "started", "slug": slug}


@app.get("/seo/programmatic/status/{slug}")
async def seo_prog_status(slug: str, _: None = Auth) -> dict:
    """
    Poll this after POSTing to /generate.
    Returns {"status": "pending"} while running,
            {"status": "done", ...page_meta} when complete,
            {"status": "error", "message": ...} on failure.
    """
    from ..seo.programmatic_seo import load_prog_store

    # Check for stored error first (consumed once read)
    if slug in _prog_errors:
        msg = _prog_errors.pop(slug)
        return {"status": "error", "message": msg}

    store = load_prog_store()
    if slug in store.get("generated", {}):
        page = store["generated"][slug]
        return {"status": "done", "slug": slug, "title": page.get("title"), "word_count": page.get("word_count")}

    # Check if a job is still actively running
    job = job_registry.get(f"prog_{slug}")
    if job and not job["task"].done():
        return {"status": "pending"}

    # Task finished but nothing in generated and no error recorded
    # This shouldn't happen, but handle it gracefully
    return {"status": "error", "message": "Generation completed but no content was saved. Check Render logs for details."}


@app.get("/seo/programmatic/generated")
async def seo_prog_generated(_: None = Auth) -> dict:
    """List all already-generated programmatic pages."""
    from ..seo.programmatic_seo import load_prog_store
    store  = load_prog_store()
    pages  = list(store.get("generated", {}).values())
    # Strip html_content to keep response small
    slim   = [{k: v for k, v in p.items() if k != "html_content"} for p in pages]
    return {"pages": slim, "count": len(slim)}


# ── SEO: Repair existing articles (one-time fix for broken markdown) ──────────

class RepairRequest(BaseModel):
    dry_run: bool = False
    force_all: bool = False   # if True, repair ALL posts (not just ones that need_repair detects)


@app.post("/seo/repair/articles")
async def seo_repair_articles(body: RepairRequest, _: None = Auth) -> dict:
    """
    Walk every published WordPress post and fix:
      - markdown links [text](url) → <a href="url">text</a>
      - pipe-style tables → proper <table>
      - en-dash sub-bullets → <li>
      - missing heading IDs (so ToC anchor links jump correctly)

    Fires a background task. Poll GET /seo/repair/status to watch progress.
    """
    if _repair_result.get("state") == "running":
        return {"status": "already_running"}

    _repair_result.update({"state": "running", "started_at": time.time(), "dry_run": body.dry_run})

    async def _do_repair():
        try:
            from ..config import load_config
            from ..publisher.wp_manager import list_posts, update_post
            from ..seo.article_repair import repair_all_posts

            cfg = load_config()
            logger.info(f"[repair] starting (dry_run={body.dry_run}, force_all={body.force_all})")
            summary = await asyncio.to_thread(
                repair_all_posts,
                cfg,
                list_posts,
                update_post,
                body.dry_run,
                body.force_all,
            )
            logger.info(f"[repair] done — {summary['repaired']}/{summary['scanned']} posts updated")
            _repair_result.update({
                "state": "done",
                "finished_at": time.time(),
                "summary": summary,
            })
        except Exception as exc:
            logger.exception(f"[repair] FAILED: {exc}")
            _repair_result.update({
                "state": "error",
                "finished_at": time.time(),
                "message": str(exc),
            })

    task = asyncio.create_task(_do_repair())
    job_registry.register("article_repair", task, "article_repair")
    return {"status": "started"}


@app.get("/seo/repair/status")
async def seo_repair_status(_: None = Auth) -> dict:
    """Poll for current state of the article-repair job."""
    return dict(_repair_result)


# ── SEO: Sitemap & Indexing ────────────────────────────────────────────────────

class IndexSubmitRequest(BaseModel):
    url: str


@app.post("/seo/index/submit")
async def seo_index_submit(body: IndexSubmitRequest, _: None = Auth) -> dict:
    """Submit a single URL to Google Indexing API + IndexNow."""
    import asyncio
    from ..config import load_config
    from ..seo.sitemap_manager import notify_search_engines

    cfg = load_config()
    return await asyncio.to_thread(notify_search_engines, body.url, cfg)


@app.post("/seo/index/batch-submit")
async def seo_batch_submit(background_tasks: BackgroundTasks, _: None = Auth) -> dict:
    """Batch-submit all posts not indexed in the past 30 days."""
    async def _do_submit():
        import asyncio
        from ..config import load_config
        from ..publisher.wp_manager import list_posts
        from ..seo.sitemap_manager import batch_submit_unindexed, ping_sitemap

        cfg    = load_config()
        posts, _, _ = await asyncio.to_thread(list_posts, cfg, 1, 100, "publish")
        urls   = [p.get("link", "") for p in posts if p.get("link")]
        result = await asyncio.to_thread(batch_submit_unindexed, urls, cfg)
        await asyncio.to_thread(ping_sitemap, cfg)
        await sse_publisher.publish("seo_index", {"type": "done", **result})

    task = asyncio.create_task(_do_submit())
    job_registry.register("seo_batch_index", task, "seo_batch_index")
    return {"status": "started"}


# ── SEO: Master Dashboard Stats ────────────────────────────────────────────────

@app.get("/seo/dashboard")
async def seo_dashboard(_: None = Auth) -> dict:
    """
    One-call endpoint that returns everything needed for the SEO dashboard:
    - Embedding count
    - Link graph stats
    - Coverage report
    - Freshness report
    - Score averages
    - Top easy-win keywords
    - Top roadmap items
    """
    import asyncio
    from ..seo.embeddings_store import load_embeddings
    from ..seo.internal_linker import get_link_stats
    from ..seo.topic_authority import get_coverage_report
    from ..seo.content_freshness import get_freshness_report
    from ..seo.seo_scorer import load_scores
    from ..seo.keyword_engine import get_easy_win_keywords
    from ..seo.topic_authority import get_top_roadmap_items

    embeddings = load_embeddings()
    scores     = load_scores()
    score_vals = [v.get("total_score", 0) for v in scores.values()]
    avg_score  = round(sum(score_vals) / max(len(score_vals), 1), 1)

    return {
        "embeddings": {
            "count": len(embeddings),
            "last_updated": max((v.get("updated_at", 0) for v in embeddings.values()), default=0),
        },
        "linking":    get_link_stats(),
        "coverage":   get_coverage_report(),
        "freshness":  get_freshness_report(),
        "scoring": {
            "articles_scored": len(scores),
            "average_score":   avg_score,
            "needs_update":    sum(1 for s in score_vals if s < 60),
        },
        "keywords":   {"easy_wins": get_easy_win_keywords(40, 5)},
        "roadmap":    {"top_items": get_top_roadmap_items("high", 5)},
    }


# ── Helpers ────────────────────────────────────────────────────────────────────


def _safe_run(run: dict) -> dict:
    """Strip internal/large fields before sending to the browser."""
    skip = {"_article_draft"}
    return {k: v for k, v in run.items() if k not in skip}
