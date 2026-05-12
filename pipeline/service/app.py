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
    """Create a new WordPress post."""
    import asyncio
    from ..config import load_config
    from ..publisher.wp_manager import create_post

    cfg = load_config()
    data = body.model_dump(exclude_none=True)
    if not data.get("title"):
        raise HTTPException(400, "title is required")
    if not data.get("content"):
        raise HTTPException(400, "content is required")
    return await asyncio.to_thread(create_post, cfg, data)


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


@app.get("/wp/categories")
async def wp_get_categories(_: None = Auth) -> dict:
    """List all WordPress categories."""
    import asyncio
    from ..config import load_config
    from ..publisher.wp_manager import get_categories

    cfg = load_config()
    cats = await asyncio.to_thread(get_categories, cfg)
    return {"categories": cats}


# ── Helpers ────────────────────────────────────────────────────────────────────


def _safe_run(run: dict) -> dict:
    """Strip internal/large fields before sending to the browser."""
    skip = {"_article_draft"}
    return {k: v for k, v in run.items() if k not in skip}
