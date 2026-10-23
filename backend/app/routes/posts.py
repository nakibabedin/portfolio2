import logging
import re
from uuid import uuid4
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_, and_, text
from typing import List, Optional
from datetime import datetime
from urllib.parse import urlparse
from app.database import get_db
from app.models.post import Post
from app.schemas.post import PostCreate, PostUpdate, PostResponse
from app.lib.s3 import delete_file_from_s3
from app.lib.feed_order import feed_ordering
from app.lib.firebase_auth import verify_firebase_token
from app.routes.shop import refresh_cached_price
from app.lib import aiko_sync, instagram_sync

logger = logging.getLogger(__name__)


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value)
    return value.strip('-')


def generate_unique_slug(title: str, db: Session, existing_post_id=None) -> str:
    base_slug = slugify(title) or f"post-{uuid4().hex[:8]}"
    slug = base_slug
    counter = 1

    while True:
        query = db.query(Post).filter(Post.slug == slug)
        if existing_post_id:
            query = query.filter(Post.id != existing_post_id)
        if not query.first():
            return slug
        slug = f"{base_slug}-{counter}" if counter < 50 else f"{base_slug}-{uuid4().hex[:4]}"
        counter += 1


router = APIRouter(prefix="/api/posts", tags=["posts"])

@router.get("/", response_model=List[PostResponse])
async def get_posts(
    category: Optional[str] = None,
    album: Optional[str] = None,
    is_major: Optional[bool] = None,
    is_favorite: Optional[bool] = None,
    limit: int = 100,
    offset: int = 0,
    sort_by: str = "date",
    pin_now_playing: bool = False,
    db: Session = Depends(get_db)
):
    """Get all posts with optional filters"""
    query = db.query(Post)
    
    if category:
        query = query.filter(Post.category == category)
    if album:
        query = query.filter(
            or_(Post.album == album, Post.cross_post_albums.any(album))
        )
    if is_major is not None:
        query = query.filter(Post.is_major == is_major)
    if is_favorite is not None:
        query = query.filter(Post.is_favorite == is_favorite)
    
    ordering = feed_ordering(Post, sort_by, pin_now_playing)

    try:
        posts = query.order_by(*ordering).limit(limit).offset(offset).all()
        return posts
    except Exception as exc:
        logger.exception("[Posts] Failed to fetch posts", extra={
            "category": category,
            "album": album,
            "is_major": is_major,
            "limit": limit,
            "offset": offset,
        })
        raise HTTPException(status_code=500, detail="Error fetching posts") from exc

@router.get("/albums/{category}")
async def get_unique_albums_by_category(
    category: str,
    db: Session = Depends(get_db)
):
    """Get unique album names from posts for a given category"""
    from sqlalchemy import func
    try:
        primary = db.query(Post.album.label('album')).filter(Post.category == category)
        cross = db.query(func.unnest(Post.cross_post_albums).label('album')).filter(Post.category == category)
        combined = primary.union(cross).subquery()
        rows = db.query(combined.c.album).distinct().all()
        album_names = [row[0] for row in rows if row[0]]
        return {"albums": sorted(album_names)}
    except Exception as e:
        print(f"[Posts] Error getting unique albums: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error fetching albums: {str(e)}")

@router.get("/instagram-locations")
async def get_instagram_locations(
    db: Session = Depends(get_db),
    current_user=Depends(verify_firebase_token),
):
    """Locations already used on posts, most used first, so the admin form can
    offer them again instead of making the Facebook page id be looked up twice."""
    from sqlalchemy import func
    uses = func.count(Post.id)
    rows = (
        db.query(Post.instagram_location_id, func.max(Post.instagram_location_name), uses)
        .filter(Post.instagram_location_id.isnot(None))
        .group_by(Post.instagram_location_id)
        .order_by(uses.desc())
        .all()
    )
    return {"locations": [{"id": row[0], "name": row[1] or row[0]} for row in rows]}

@router.get("/{post_id}", response_model=PostResponse)
async def get_post(post_id: str, db: Session = Depends(get_db)):
    """Get a single post by ID"""
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return post

@router.get("/slug/{slug}", response_model=PostResponse)
async def get_post_by_slug(slug: str, db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.slug == slug).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return post

@router.post("/", response_model=PostResponse)
async def create_post(
    post: PostCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(verify_firebase_token),
):
    """Create a new post"""
    data = post.dict(exclude_unset=True)
    # An instruction for this request, not a column. Popped before Post(**data).
    # Read off the model, not the dict: exclude_unset drops it when the client
    # leaves it out, and leaving it out has to mean the schema's default (on).
    data.pop('post_to_instagram', None)
    post_to_instagram = post.post_to_instagram

    title = data.get('title')
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")

    slug = data.get('slug') or generate_unique_slug(title, db)
    data['slug'] = slug

    category = data.get('category')
    is_major = data.get('is_major', False)

    if 'gallery_urls' not in data or data['gallery_urls'] is None:
        data['gallery_urls'] = []

    if is_major and category in {'art', 'photo'}:
        if not data.get('splash_image_url'):
            data['splash_image_url'] = data.get('content_url')
    else:
        if not data.get('splash_image_url'):
            data['splash_image_url'] = data.get('thumbnail_url')

    db_post = Post(**data)
    if db_post.printify_product_id:
        refresh_cached_price(db_post)
    db.add(db_post)
    db.commit()
    db.refresh(db_post)

    # Mirror art/photo to Aiko, and new photos on to Instagram. Backgrounded so a
    # slow or unreachable Aiko or Instagram never delays — or fails — publishing
    # here. Instagram goes through mirror_then_publish, which does the Aiko push
    # itself first so the caption can link to the pin it creates, and only ever
    # follows a mirrored post. Unlike the Aiko mirror there is no Instagram
    # counterpart in update_post: Instagram exposes no way to delete a post or
    # change its caption, so it happens once, here.
    snapshot = aiko_sync.snapshot(db_post)
    ig_snapshot = instagram_sync.snapshot(db_post)
    if (
        post_to_instagram
        and aiko_sync.should_mirror(snapshot)
        and aiko_sync.is_configured()
        and instagram_sync.is_configured()
        and instagram_sync.should_publish(ig_snapshot)
    ):
        background_tasks.add_task(instagram_sync.mirror_then_publish, snapshot, ig_snapshot)
    elif aiko_sync.should_mirror(snapshot):
        background_tasks.add_task(aiko_sync.push_post, snapshot)

    return db_post

@router.put("/{post_id}", response_model=PostResponse)
async def update_post(
    post_id: str,
    post_update: PostUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(verify_firebase_token)
):
    """Update an existing post"""
    db_post = db.query(Post).filter(Post.id == post_id).first()
    if not db_post:
        raise HTTPException(status_code=404, detail="Post not found")

    # Captured before the update is applied: an edit that unpublishes a post or
    # moves it out of art/photo has to take the Aiko pin down, and afterwards
    # there is no way to tell that from a post that was never mirrored.
    was_mirrored = aiko_sync.should_mirror(aiko_sync.snapshot(db_post))

    update_payload = post_update.dict(exclude_unset=True)
    previous_content_url = db_post.content_url

    for key, value in update_payload.items():
        setattr(db_post, key, value)

    if 'title' in update_payload and not update_payload.get('slug'):
        db_post.slug = generate_unique_slug(db_post.title, db, existing_post_id=db_post.id)

    if (
        ('thumbnail_url' in update_payload or 'content_url' in update_payload or 'is_major' in update_payload or 'category' in update_payload)
        and 'splash_image_url' not in update_payload
    ):
        if db_post.is_major and db_post.category in {'art', 'photo'}:
            db_post.splash_image_url = db_post.content_url
        elif not db_post.splash_image_url:
            db_post.splash_image_url = db_post.thumbnail_url

    # Linking a shop post to a Printify product brings its "from" price along.
    if update_payload.get('printify_product_id'):
        refresh_cached_price(db_post)
 
    db.commit()
    db.refresh(db_post)

    # A replaced file (e.g. a new resume PDF) leaves the old one orphaned in S3.
    # Only delete it once nothing on the post still points at it. Projects keep
    # article text in content_url, so anything that isn't an S3 URL is skipped.
    if (
        previous_content_url
        and urlparse(previous_content_url).netloc.endswith('.amazonaws.com')
        and previous_content_url != db_post.content_url
        and previous_content_url not in (db_post.thumbnail_url, db_post.splash_image_url)
    ):
        delete_file_from_s3(previous_content_url)

    background_tasks.add_task(aiko_sync.sync_post, aiko_sync.snapshot(db_post), was_mirrored)

    return db_post

# Post ids with an Instagram publish under way, so a double click can't start a
# second one before the first has written instagram_media_id back.
_instagram_in_flight: set[str] = set()

@router.post("/{post_id}/instagram", response_model=PostResponse)
async def publish_post_to_instagram(
    post_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(verify_firebase_token),
):
    """Post an already-published photo to Instagram, through Aiko.

    The same path a new photo takes on create, run on request for posts that
    predate it or were created with the switch off. Waits for the result rather
    than backgrounding it, so the admin sees whether it went out.
    """
    db_post = db.query(Post).filter(Post.id == post_id).first()
    if not db_post:
        raise HTTPException(status_code=404, detail="Post not found")

    snapshot = aiko_sync.snapshot(db_post)
    ig_snapshot = instagram_sync.snapshot(db_post)
    if db_post.instagram_media_id:
        raise HTTPException(status_code=409, detail="Already posted to Instagram")
    if not aiko_sync.should_mirror(snapshot):
        raise HTTPException(status_code=400, detail="Only photos posted to Aiko can go to Instagram")
    if not instagram_sync.should_publish(ig_snapshot):
        raise HTTPException(status_code=400, detail="Only photo posts can go to Instagram")
    if not (aiko_sync.is_configured() and instagram_sync.is_configured()):
        raise HTTPException(status_code=503, detail="Aiko or Instagram isn't configured on the server")
    if post_id in _instagram_in_flight:
        raise HTTPException(status_code=409, detail="Already being posted to Instagram")

    _instagram_in_flight.add(post_id)
    try:
        result = await instagram_sync.mirror_then_publish(snapshot, ig_snapshot)
    finally:
        _instagram_in_flight.discard(post_id)

    if not result.get("ok"):
        if result.get("error") == "aiko push failed":
            detail = "Aiko didn't take this photo, so it wasn't posted to Instagram"
        else:
            detail = f"Instagram didn't take it: {result.get('error')}"
        raise HTTPException(status_code=502, detail=detail)

    # publish_and_record wrote the media id through its own session.
    db.refresh(db_post)
    return db_post

@router.delete("/{post_id}")
async def delete_post(
    post_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(verify_firebase_token),
):
    """Delete a post"""
    db_post = db.query(Post).filter(Post.id == post_id).first()
    if not db_post:
        raise HTTPException(status_code=404, detail="Post not found")

    content_url = db_post.content_url
    thumbnail_url = db_post.thumbnail_url
    # A photo group's other photos were uploaded for it alone. Shop galleries
    # are left as they always have been.
    gallery_urls = [
        u for u in (db_post.gallery_urls or [])
        if db_post.category == 'photo' and u not in (content_url, thumbnail_url)
    ]
    aiko_snapshot = aiko_sync.snapshot(db_post)
    was_mirrored = aiko_sync.should_mirror(aiko_snapshot)

    db.delete(db_post)
    db.commit()

    if was_mirrored:
        background_tasks.add_task(aiko_sync.delete_post, aiko_snapshot)

    # Delete associated assets from S3 (best-effort)
    delete_file_from_s3(content_url)
    if thumbnail_url and thumbnail_url != content_url:
        delete_file_from_s3(thumbnail_url)
    for url in gallery_urls:
        delete_file_from_s3(url)
    return {"message": "Post deleted successfully"}

