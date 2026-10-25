import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from pydantic import ValidationError

from app.lib import instagram_sync
from app.schemas.post import PostUpdate


def _post(**overrides):
    fields = dict(
        id="p1",
        title="Title",
        description="A walk by the water",
        instagram_hashtags=[],
        instagram_user_tags=[],
    )
    fields.update(overrides)
    return SimpleNamespace(**fields)


class SchemaTests(unittest.TestCase):
    def test_hashtags_are_stored_bare_and_deduped(self):
        update = PostUpdate(instagram_hashtags=["#Film", "film", "nex-5n", " ", "golden hour"])
        self.assertEqual(update.instagram_hashtags, ["Film", "nex5n", "goldenhour"])

    def test_too_many_hashtags(self):
        with self.assertRaises(ValidationError):
            PostUpdate(instagram_hashtags=[f"tag{i}" for i in range(31)])

    def test_user_tags_are_bare_lowercase_usernames(self):
        update = PostUpdate(instagram_user_tags=["@Some.One", "some.one", "two_2"])
        self.assertEqual(update.instagram_user_tags, ["some.one", "two_2"])

    def test_user_tag_limits(self):
        with self.assertRaises(ValidationError):
            PostUpdate(instagram_user_tags=[f"user{i}" for i in range(21)])
        with self.assertRaises(ValidationError):
            PostUpdate(instagram_user_tags=["not a username"])


class CaptionTests(unittest.TestCase):
    def test_text_then_link_then_hashtags(self):
        caption = instagram_sync._caption(_post(instagram_hashtags=["film", "nyc"]), "https://aiko/pin/1")
        self.assertEqual(caption, "A walk by the water\n\nhttps://aiko/pin/1\n\n#film #nyc")

    def test_long_text_is_trimmed_not_the_tail(self):
        post = _post(description="x" * 3000, instagram_hashtags=["film"])
        caption = instagram_sync._caption(post, "https://aiko/pin/1")
        self.assertEqual(len(caption), instagram_sync.MAX_CAPTION)
        self.assertTrue(caption.endswith("https://aiko/pin/1\n\n#film"))

    def test_user_tag_params(self):
        self.assertEqual(instagram_sync._user_tag_params(_post()), {})
        params = instagram_sync._user_tag_params(_post(instagram_user_tags=["a.b", "c_d"]))
        self.assertEqual(
            json.loads(params["user_tags"]),
            [{"username": "a.b", "x": 0.333, "y": 0.5}, {"username": "c_d", "x": 0.667, "y": 0.5}],
        )


class _Response:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body or {}
        self.text = json.dumps(self._body)
        self.content = b"image"

    def json(self):
        return self._body

    def raise_for_status(self):
        pass


class _Client:
    """Stands in for httpx.AsyncClient: refuses any container that tags
    people, accepts everything else."""

    def __init__(self, *args, **kwargs):
        self.containers = []

    async def __aenter__(self):
        _Client.last = self
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        return _Response(200)

    async def post(self, url, data):
        if url.endswith("/media"):
            self.containers.append(data)
            if "user_tags" in data:
                return _Response(400, {"error": {"message": "Invalid user id"}})
            return _Response(200, {"id": "c1"})
        return _Response(200, {"id": "m1"})


class RetryTests(unittest.TestCase):
    def _publish(self, images):
        post = _post(content_url=images[0], instagram_user_tags=["gone.private"])
        with (
            mock.patch.object(instagram_sync, "_config", return_value=("https://graph", "u", "t")),
            mock.patch.object(instagram_sync.aiko_sync, "group_images", return_value=images),
            mock.patch.object(instagram_sync, "_prepare_jpeg", return_value="https://s3/x.jpg"),
            mock.patch.object(instagram_sync, "_aspect_of", return_value=1.0),
            mock.patch.object(instagram_sync, "_wait_for_container", return_value=None),
            mock.patch.object(instagram_sync.httpx, "AsyncClient", _Client),
        ):
            return asyncio.run(instagram_sync.publish_post(post, "https://aiko/pin/1"))

    def test_publishes_untagged_when_instagram_refuses_the_tags(self):
        result = self._publish(["https://s3/x.webp"])
        self.assertEqual(result, {"ok": True, "media_id": "m1"})
        first, retry = _Client.last.containers
        self.assertIn("user_tags", first)
        self.assertNotIn("user_tags", retry)
        self.assertEqual(retry["caption"], first["caption"])

    def test_carousel_tags_go_on_the_first_photo(self):
        result = self._publish(["https://s3/a.webp", "https://s3/b.webp"])
        self.assertEqual(result, {"ok": True, "media_id": "m1"})
        tagged, first, second, carousel = _Client.last.containers
        self.assertIn("user_tags", tagged)
        self.assertEqual(tagged["is_carousel_item"], "true")
        self.assertNotIn("user_tags", first)
        self.assertNotIn("user_tags", second)
        self.assertEqual(carousel["media_type"], "CAROUSEL")
        self.assertNotIn("user_tags", carousel)


if __name__ == "__main__":
    unittest.main()
