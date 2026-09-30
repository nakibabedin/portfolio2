"""Publish art and photo posts to Instagram, on request.

This is deliberately *not* shaped like :mod:`app.lib.aiko_sync`, even though the
two do a similar-sounding job. Aiko is a mirror: it reconciles on every edit and
takes pins down when a post stops qualifying. Instagram cannot be mirrored --
the Graph API has no endpoint to delete a published post or edit its caption, so
a push here is one-way and permanent.

Three rules follow from that:

- **Opt in, every time.** ``post_to_instagram`` defaults to False on
  ``PostCreate``. Nothing reaches Instagram unless the admin flipped the toggle
  for that specific post. There is no "mirror everything" mode, on purpose.
- **Exactly once.** ``instagram_media_id`` is written back after a successful
  publish and is the guard against double-posting. A post that already carries
  one is skipped, so re-saving or re-running a backfill cannot duplicate it.
- **Never break a save.** Like the Aiko mirror, every push runs as a FastAPI
  background task and swallows its own errors. Instagram being down, rate
  limited, or holding an expired token must not fail publishing on the site.

The format work in :func:`_prepare_jpeg` exists because the site's own upload
pipeline converts everything to WebP, and Instagram's ``image_url`` accepts
**JPEG only** -- it also rejects anything outside a 4:5 to 1.91:1 aspect ratio.
So the image the site serves is never the image Instagram is handed; a JPEG
derivative is rendered and parked in S3 under ``instagram/`` at publish time.
Those derivatives are not tracked on the post and are not cleaned up when a post
is deleted; they are a few hundred KB each and orphaning them is cheaper than
carrying another column and another delete path for them.
"""

import asyncio
import io
import logging
import os
from types import SimpleNamespace
from typing import Optional

import httpx
from PIL import Image

from app.database import SessionLocal
from app.lib.s3 import upload_file_to_s3
from app.models.post import Post

logger = logging.getLogger(__name__)

# Same two image-holding categories the Aiko mirror uses.
PUBLISHABLE_CATEGORIES = {"art", "photo"}

# Art and photo posts are created without a post_type in practice; the field is
# only set for the audio/video/file posts other categories carry.
PUBLISHABLE_POST_TYPES = {None, "", "photo", "image"}

# Instagram's feed limits. Outside this ratio range the container is rejected,
# so anything taller or wider is padded to the nearest bound rather than failing.
MIN_ASPECT = 4 / 5      # 0.8, portrait bound
MAX_ASPECT = 1.91       # landscape bound

# Instagram downsizes anything wider than this anyway; doing it here keeps the
# JPEG small enough to stay well under the 8MB fetch limit.
MAX_WIDTH = 1440

# Captions are capped at 2200 characters.
MAX_CAPTION = 2200

# Fetching the image from S3 and rendering the container is Meta-side work; it
# is usually instant for a photo but is allowed to be slow.
_TIMEOUT = httpx.Timeout(120.0)

# How long to wait for a container to finish before giving up.
_STATUS_ATTEMPTS = 10
_STATUS_DELAY = 3.0


def _config() -> Optional[tuple[str, str, str]]:
    """``(base_url, ig_user_id, access_token)``, or None when unconfigured.

    Unset means "no Instagram" rather than an error, matching the Aiko mirror:
    local dev and any environment without credentials runs normally with pushes
    skipped, and the toggle in the admin simply does nothing.
    """
    user_id = os.getenv("INSTAGRAM_USER_ID", "").strip()
    token = os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()
    if not user_id or not token:
        return None
    version = os.getenv("INSTAGRAM_GRAPH_VERSION", "v23.0").strip().strip("/")
    host = os.getenv("INSTAGRAM_GRAPH_HOST", "https://graph.instagram.com").strip().rstrip("/")
    return f"{host}/{version}", user_id, token


def is_configured() -> bool:
    return _config() is not None


def snapshot(post) -> SimpleNamespace:
    """Detach the fields the push needs from the SQLAlchemy instance.

    Background tasks run *after* the request's session is closed, so reading a
    lazy attribute off the live ORM object at that point raises
    ``DetachedInstanceError``. Same reasoning as ``aiko_sync.snapshot``.
    """
    return SimpleNamespace(
        id=post.id,
        title=post.title,
        description=post.description,
        category=post.category,
        post_type=post.post_type,
        content_url=post.content_url,
        thumbnail_url=post.thumbnail_url,
        instagram_media_id=post.instagram_media_id,
    )


def _image_url(post) -> Optional[str]:
    """The full-size image to publish, matching the Aiko mirror's preference."""
    return (post.content_url or "").strip() or (post.thumbnail_url or "").strip() or None


def should_publish(post) -> bool:
    """Whether this post *can* go to Instagram -- not whether it was asked to.

    The admin's toggle decides intent; this decides eligibility. An art or photo
    post, with a fetchable image, that has not already been published.
    """
    if post.instagram_media_id:
        return False
    if post.category not in PUBLISHABLE_CATEGORIES:
        return False
    if (post.post_type or None) not in PUBLISHABLE_POST_TYPES:
        return False

    image_url = _image_url(post)
    return bool(image_url and image_url.startswith(("http://", "https://")))


def _caption(post) -> str:
    """Title, then description. No link -- Instagram captions are not clickable,
    so a bare URL is noise rather than navigation."""
    title = (post.title or "").strip()
    description = (post.description or "").strip()
    caption = "\n\n".join(part for part in (title, description) if part)
    if len(caption) > MAX_CAPTION:
        caption = caption[: MAX_CAPTION - 1].rstrip() + "…"
    return caption


def _pad_to_aspect(img: Image.Image) -> Image.Image:
    """Letterbox the image onto white until its ratio is one Instagram accepts.

    Cropping would be the other option and is what most tools do, but this site
    is a portfolio -- silently trimming the edge off a piece of art is worse
    than a white border around it.
    """
    width, height = img.size
    aspect = width / height

    if MIN_ASPECT <= aspect <= MAX_ASPECT:
        return img

    if aspect < MIN_ASPECT:
        # Too tall: widen the canvas.
        target_width = int(round(height * MIN_ASPECT))
        target_height = height
    else:
        # Too wide: heighten the canvas.
        target_width = width
        target_height = int(round(width / MAX_ASPECT))

    canvas = Image.new("RGB", (target_width, target_height), (255, 255, 255))
    canvas.paste(img, ((target_width - width) // 2, (target_height - height) // 2))
    return canvas


def _prepare_jpeg(image_bytes: bytes, post_id: str) -> str:
    """Render an Instagram-acceptable JPEG into S3 and return its public URL.

    Raises on failure; the caller turns that into a logged, non-fatal outcome.
    """
    img = Image.open(io.BytesIO(image_bytes))

    # Flatten transparency onto white rather than letting JPEG turn it black.
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        background = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(background, img).convert("RGB")
    elif img.mode != "RGB":
        img = img.convert("RGB")

    img = _pad_to_aspect(img)

    if img.width > MAX_WIDTH:
        ratio = MAX_WIDTH / img.width
        img = img.resize((MAX_WIDTH, int(img.height * ratio)), Image.Resampling.LANCZOS)

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=90, optimize=True, progressive=True)

    return upload_file_to_s3(
        file_content=buffer.getvalue(),
        file_name=f"{post_id}.jpg",
        content_type="image/jpeg",
        folder="instagram",
    )


async def _wait_for_container(
    client: httpx.AsyncClient, base_url: str, container_id: str, token: str
) -> Optional[str]:
    """Poll until Meta has finished fetching and processing the image.

    Returns an error string, or None when the container is ready. Images are
    usually FINISHED on the first check; the polling is here for the case where
    S3 is slow enough that publishing immediately would race the fetch.
    """
    for attempt in range(_STATUS_ATTEMPTS):
        response = await client.get(
            f"{base_url}/{container_id}",
            params={"fields": "status_code,status", "access_token": token},
        )
        if response.status_code >= 400:
            return f"status check failed: {response.status_code} {response.text[:200]}"

        body = response.json()
        status_code = body.get("status_code")
        if status_code == "FINISHED":
            return None
        if status_code == "ERROR":
            return f"container errored: {body.get('status', 'unknown')}"
        if status_code == "EXPIRED":
            return "container expired before publishing"

        if attempt < _STATUS_ATTEMPTS - 1:
            await asyncio.sleep(_STATUS_DELAY)

    return "container never finished processing"


async def publish_post(post) -> dict:
    """Publish this post to Instagram. Never raises.

    Returns an outcome dict -- ``{"ok": True, "media_id": ...}`` or
    ``{"ok": False, "error": ...}``. Callers fire this as a background task and
    ignore the return; a script can use it to report per-post results.
    """
    config = _config()
    if not config:
        return {"ok": False, "error": "instagram not configured"}

    base_url, user_id, token = config
    post_id = str(post.id)
    source_url = _image_url(post)

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            # 1. Pull the site's own image and re-render it as a JPEG Instagram
            #    will accept. Done here rather than in the upload route so the
            #    site keeps serving WebP and the conversion cost is only paid
            #    by posts that actually go to Instagram.
            source = await client.get(source_url)
            source.raise_for_status()
            jpeg_url = await asyncio.to_thread(_prepare_jpeg, source.content, post_id)

            # 2. Create the media container.
            create = await client.post(
                f"{base_url}/{user_id}/media",
                data={
                    "image_url": jpeg_url,
                    "caption": _caption(post),
                    "access_token": token,
                },
            )
            if create.status_code >= 400:
                detail = create.text[:300]
                logger.warning(
                    "[instagram] container failed for post %s: %s %s",
                    post_id, create.status_code, detail,
                )
                return {"ok": False, "status": create.status_code, "error": detail}

            container_id = create.json().get("id")
            if not container_id:
                return {"ok": False, "error": "no container id returned"}

            # 3. Wait for Meta to finish fetching the JPEG.
            wait_error = await _wait_for_container(client, base_url, container_id, token)
            if wait_error:
                logger.warning("[instagram] post %s not publishable: %s", post_id, wait_error)
                return {"ok": False, "error": wait_error}

            # 4. Publish it. This is the irreversible step -- there is no API to
            #    undo it, which is why the toggle defaults to off.
            publish = await client.post(
                f"{base_url}/{user_id}/media_publish",
                data={"creation_id": container_id, "access_token": token},
            )
            if publish.status_code >= 400:
                detail = publish.text[:300]
                logger.warning(
                    "[instagram] publish failed for post %s: %s %s",
                    post_id, publish.status_code, detail,
                )
                return {"ok": False, "status": publish.status_code, "error": detail}

            media_id = publish.json().get("id")
            logger.info("[instagram] published post %s as media %s", post_id, media_id)
            return {"ok": True, "media_id": media_id}

    except httpx.HTTPError as exc:
        logger.warning("[instagram] could not reach Instagram for post %s: %s", post_id, exc)
        return {"ok": False, "error": f"unreachable: {exc}"}
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[instagram] unexpected publish failure for post %s: %s", post_id, exc)
        return {"ok": False, "error": str(exc)}


async def publish_and_record(post) -> dict:
    """Publish, then write the media id back so it can never post twice.

    The background task runs after the request's session is closed, so this
    opens its own. A failure to record is logged but not raised -- the post is
    already live on Instagram at that point and nothing here can undo it.
    """
    result = await publish_post(post)
    if not result.get("ok"):
        return result

    media_id = result.get("media_id")
    if not media_id:
        return result

    def _record() -> None:
        db = SessionLocal()
        try:
            db.query(Post).filter(Post.id == post.id).update(
                {"instagram_media_id": str(media_id)}
            )
            db.commit()
        finally:
            db.close()

    try:
        await asyncio.to_thread(_record)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "[instagram] published post %s as media %s but could not record it: %s",
            post.id, media_id, exc,
        )

    return result
