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
        instagram_collaborators=[],
        instagram_location_id=None,
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

    def test_collaborators_are_bare_lowercase_usernames(self):
        update = PostUpdate(instagram_collaborators=["@Some.One", "some.one", "two_2"])
        self.assertEqual(update.instagram_collaborators, ["some.one", "two_2"])

    def test_collaborator_limits(self):
        with self.assertRaises(ValidationError):
            PostUpdate(instagram_collaborators=["a", "b", "c", "d"])
        with self.assertRaises(ValidationError):
            PostUpdate(instagram_collaborators=["not a username"])

    def test_location_id_is_digits_or_nothing(self):
        self.assertEqual(PostUpdate(instagram_location_id=" 108424279189115 ").instagram_location_id, "108424279189115")
        self.assertIsNone(PostUpdate(instagram_location_id="").instagram_location_id)
        with self.assertRaises(ValidationError):
            PostUpdate(instagram_location_id="facebook.com/somewhere")


class CaptionTests(unittest.TestCase):
    def test_text_then_link_then_hashtags(self):
        caption = instagram_sync._caption(_post(instagram_hashtags=["film", "nyc"]), "https://aiko/pin/1")
        self.assertEqual(caption, "A walk by the water\n\nhttps://aiko/pin/1\n\n#film #nyc")

    def test_long_text_is_trimmed_not_the_tail(self):
        post = _post(description="x" * 3000, instagram_hashtags=["film"])
        caption = instagram_sync._caption(post, "https://aiko/pin/1")
        self.assertEqual(len(caption), instagram_sync.MAX_CAPTION)
        self.assertTrue(caption.endswith("https://aiko/pin/1\n\n#film"))

    def test_discovery_params(self):
        self.assertEqual(instagram_sync._discovery_params(_post()), {})
        params = instagram_sync._discovery_params(
            _post(instagram_location_id="123456", instagram_collaborators=["a.b"])
        )
        self.assertEqual(params["location_id"], "123456")
        self.assertEqual(json.loads(params["collaborators"]), ["a.b"])


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
    """Stands in for httpx.AsyncClient: refuses the first container if it
    carries collaborators, accepts everything else."""

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
            if "collaborators" in data:
                return _Response(400, {"error": {"message": "Invalid user id"}})
            return _Response(200, {"id": "c1"})
        return _Response(200, {"id": "m1"})


class RetryTests(unittest.TestCase):
    def test_publishes_without_extras_when_instagram_refuses_them(self):
        post = _post(
            content_url="https://s3/x.webp",
            instagram_collaborators=["gone.private"],
            instagram_location_id="123456",
        )
        with (
            mock.patch.object(instagram_sync, "_config", return_value=("https://graph", "u", "t")),
            mock.patch.object(instagram_sync.aiko_sync, "group_images", return_value=["https://s3/x.webp"]),
            mock.patch.object(instagram_sync, "_prepare_jpeg", return_value="https://s3/x.jpg"),
            mock.patch.object(instagram_sync, "_wait_for_container", return_value=None),
            mock.patch.object(instagram_sync.httpx, "AsyncClient", _Client),
        ):
            result = asyncio.run(instagram_sync.publish_post(post, "https://aiko/pin/1"))

        self.assertEqual(result, {"ok": True, "media_id": "m1"})
        first, retry = _Client.last.containers
        self.assertIn("location_id", first)
        self.assertNotIn("collaborators", retry)
        self.assertNotIn("location_id", retry)
        self.assertEqual(retry["caption"], first["caption"])


if __name__ == "__main__":
    unittest.main()
