"""Mirror art and photo posts into Aiko.

Publishing a piece here should put it on Aiko without a second upload. Aiko owns
the hard part — it pulls the image into its own bucket, moderates it, dedupes
it, and queues thumbnailing and the CLIP embedding — so this module's whole job
is deciding *which* posts qualify and pushing them at the right moments.

Two rules shape everything below:

- **Never break an admin save.** Every push runs as a FastAPI background task
  and swallows its own errors. If Aiko is down, mid-deploy, or misconfigured,
  saving a post here still succeeds; the mirror is repaired by the next edit.
- **The qualifying set is the contract.** ``should_mirror`` decides membership,
  and any transition *out* of that set — recategorizing art to music, clearing
  the image, deleting the post — is a delete on Aiko's side, not a no-op.
  Otherwise a post pulled from the site would live on in Aiko forever.
"""

import hashlib
import logging
import os
from types import SimpleNamespace
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# The two categories that hold images. Kept in sync with the art/photo pairing
# posts.py already uses for splash images.
MIRRORED_CATEGORIES = {"art", "photo"}

# Non-image post types never mirror even inside those categories. None is in the
# set because art and photo posts are created without a post_type in practice —
# the field is only set for the audio/video/file posts other categories carry.
MIRRORED_POST_TYPES = {None, "", "photo", "image"}

_TIMEOUT = httpx.Timeout(60.0)


def _config() -> Optional[tuple[str, str]]:
    """``(base_url, secret)``, or None when the mirror isn't configured.

    Unset means "no mirror" rather than an error: local dev and any environment
    without Aiko credentials runs normally with pushes skipped.
    """
    base_url = os.getenv("AIKO_INGEST_URL", "").strip().rstrip("/")
    secret = os.getenv("AIKO_INGEST_SECRET", "").strip()
    if not base_url or not secret:
        return None
    return base_url, secret


def is_configured() -> bool:
    return _config() is not None


def snapshot(post) -> SimpleNamespace:
    """Detach the fields the mirror needs from the SQLAlchemy instance.

    Pushes run as background tasks, which execute *after* the request's session
    is closed. Reading a lazy attribute off the live ORM object at that point
    raises ``DetachedInstanceError``, so the values are copied out while the
    session is still open.
    """
    return SimpleNamespace(
        id=post.id,
        title=post.title,
        description=post.description,
        category=post.category,
        post_type=post.post_type,
        content_url=post.content_url,
        thumbnail_url=post.thumbnail_url,
        slug=post.slug,
        mirror_to_aiko=post.mirror_to_aiko,
        gallery_urls=list(post.gallery_urls or []),
    )


def should_mirror(post) -> bool:
    """Whether this post belongs on Aiko.

    An art or photo post with a fetchable image, and that is all. There is
    deliberately no ``is_active`` check: despite the name, that flag is a
    projects-only "currently active" badge — the admin's toggle is disabled for
    anything that isn't a project, nothing filters the feed by it, and every one
    of the site's art and photo posts has it False while being live. Gating on
    it would mirror nothing, forever. A post existing here *is* it being
    published; the site has no draft state.

    ``mirror_to_aiko`` is the admin's opt-out. Switching it off on an edit is a
    transition out of the set like any other, so the pin comes down.
    """
    if post.mirror_to_aiko is False:
        return False
    if post.category not in MIRRORED_CATEGORIES:
        return False
    if (post.post_type or None) not in MIRRORED_POST_TYPES:
        return False

    image_url = _image_url(post)
    return bool(image_url and image_url.startswith(("http://", "https://")))


def _image_url(post) -> Optional[str]:
    """The full-size image to mirror.

    ``content_url`` is the original upload; ``thumbnail_url`` is the fallback for
    older posts that only ever had one. Data URLs are rejected by the caller's
    ``startswith`` check — Aiko needs something it can fetch.
    """
    return (post.content_url or "").strip() or (post.thumbnail_url or "").strip() or None


def group_images(post) -> list[str]:
    """Every image this post publishes, in order: a photo group's photos, or
    the one image of any other post.

    A photo group keeps its photos in ``gallery_urls`` with the cover first (the
    same URL as ``content_url``). Anything else -- including art, and the shop's
    product galleries -- is a single image as far as Aiko and Instagram go.
    """
    cover = _image_url(post)
    gallery = [u.strip() for u in (post.gallery_urls or []) if u and u.strip()]
    if post.category == "photo" and len(gallery) > 1:
        seen: set[str] = set()
        images = [u for u in gallery if not (u in seen or seen.add(u))]
        return [u for u in images if u.startswith(("http://", "https://"))]
    return [cover] if cover else []


def _source_ids(post) -> list[tuple[str, str]]:
    """``(source_id, image_url)`` for each pin this post owns on Aiko.

    A single image keeps the post id as its source id, as it always has, so
    pins mirrored before groups existed are untouched. Each photo in a group is
    its own pin, keyed by the post and the photo rather than its position, so
    the key stays with the photo.
    """
    images = group_images(post)
    if len(images) <= 1:
        return [(str(post.id), url) for url in images]
    return [
        (f"{post.id}:{hashlib.sha1(url.encode()).hexdigest()[:16]}", url)
        for url in images
    ]


def _public_url(post) -> Optional[str]:
    """The page on this site the Aiko pin should link back to."""
    site_url = os.getenv("PORTFOLIO_PUBLIC_URL", "").strip().rstrip("/")
    if not site_url or not post.slug:
        return None
    return f"{site_url}/{post.category}/{post.slug}"


def pin_url(pin_id) -> str:
    """The public Aiko page for a pin, as Aiko's own share button builds it."""
    site_url = os.getenv("AIKO_PUBLIC_URL", "https://www.try-aiko.com").strip().rstrip("/")
    return f"{site_url}/pin/{pin_id}"


def _description(post) -> str:
    """Aiko shows a single description field."""
    return (post.description or "").strip()


async def push_post(post) -> dict:
    """Create or refresh this post's pins on Aiko -- one, or one per photo in a
    group. Never raises.

    Returns the cover's outcome dict — ``{"ok": True, "pin_id": ..., ...}`` or
    ``{"ok": False, "error": ...}`` — since the cover's pin is the one the
    Instagram caption links to. The other photos' failures are logged. The
    route handlers fire this as a background task and ignore the return; the
    backfill script uses it to report per-post results.
    """
    config = _config()
    if not config:
        return {"ok": False, "error": "mirror not configured"}

    results = [
        await _push_one(config, post, source_id, image_url)
        for source_id, image_url in _source_ids(post)
    ]
    if not results:
        return {"ok": False, "error": "no image"}
    return results[0]


async def _push_one(config: tuple[str, str], post, source_id: str, image_url: str) -> dict:
    base_url, secret = config
    payload = {
        "source_id": source_id,
        "title": post.title,
        "description": _description(post),
        "image_url": image_url,
        "source_url": _public_url(post),
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                f"{base_url}/ingest/portfolio",
                json=payload,
                headers={"X-Ingest-Secret": secret},
            )
        if response.status_code >= 400:
            # 422 is Aiko's moderation rejection — worth seeing in the log as
            # its own thing, since the post is live here but will never appear
            # there until it's changed.
            detail = response.text[:300]
            logger.warning(
                "[aiko] push failed for post %s: %s %s",
                source_id, response.status_code, detail,
            )
            return {"ok": False, "status": response.status_code, "error": detail}
        result = response.json()
        logger.info("[aiko] pushed post %s: %s", source_id, result)
        return {"ok": True, **result}
    except httpx.HTTPError as exc:
        logger.warning("[aiko] could not reach Aiko for post %s: %s", source_id, exc)
        return {"ok": False, "error": f"unreachable: {exc}"}
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[aiko] unexpected push failure for post %s: %s", source_id, exc)
        return {"ok": False, "error": str(exc)}


async def delete_post(post) -> None:
    """Remove this post's pins from Aiko. Takes a snapshot, not an id: a photo
    group's pins are keyed by its photos. Never raises.

    Safe to call for a post that was never mirrored; Aiko answers 404 and that
    is treated as success.
    """
    config = _config()
    if not config:
        return

    for source_id, _ in _source_ids(post):
        await _delete_one(config, source_id)


async def _delete_one(config: tuple[str, str], source_id: str) -> None:
    base_url, secret = config

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.delete(
                f"{base_url}/ingest/portfolio/{source_id}",
                headers={"X-Ingest-Secret": secret},
            )
        if response.status_code == 404:
            return
        if response.status_code >= 400:
            logger.warning(
                "[aiko] delete failed for post %s: %s %s",
                source_id, response.status_code, response.text[:300],
            )
            return
        logger.info("[aiko] removed pin for post %s", source_id)
    except httpx.HTTPError as exc:
        logger.warning("[aiko] could not reach Aiko to delete post %s: %s", source_id, exc)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[aiko] unexpected delete failure for post %s: %s", source_id, exc)


async def sync_post(post, was_mirrored: bool) -> None:
    """Reconcile Aiko with a post's current state after an edit.

    ``was_mirrored`` is the qualifying verdict from *before* the update was
    applied. It is what distinguishes "still not on Aiko, do nothing" from "was
    on Aiko and no longer qualifies, take it down" — the case that would
    otherwise strand a pin for a post the site no longer shows.
    """
    if should_mirror(post):
        await push_post(post)
    elif was_mirrored:
        await delete_post(post)
