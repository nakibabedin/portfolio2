import unittest
from types import SimpleNamespace

from app.routes.posts import stored_files

S3 = "https://bucket.s3.us-east-1.amazonaws.com"


def post(**fields):
    base = dict(content_url=None, thumbnail_url=None, splash_image_url=None, gallery_urls=[])
    return SimpleNamespace(**{**base, **fields})


class StoredFilesTests(unittest.TestCase):
    def test_reordered_listing_orphans_nothing(self):
        before = post(content_url=f"{S3}/a.jpg", thumbnail_url=f"{S3}/a.jpg",
                      gallery_urls=[f"{S3}/a.jpg", f"{S3}/b.jpg"])
        after = post(content_url=f"{S3}/b.jpg", thumbnail_url=f"{S3}/b.jpg",
                     gallery_urls=[f"{S3}/b.jpg", f"{S3}/a.jpg"])
        self.assertEqual(stored_files(before) - stored_files(after), set())

    def test_dropped_photo_and_old_thumbnail_are_orphaned(self):
        before = post(content_url=f"{S3}/a.jpg", thumbnail_url=f"{S3}/thumb.jpg",
                      splash_image_url=f"{S3}/thumb.jpg",
                      gallery_urls=[f"{S3}/a.jpg", f"{S3}/b.jpg"])
        after = post(content_url=f"{S3}/a.jpg", thumbnail_url=f"{S3}/a.jpg",
                     splash_image_url=f"{S3}/a.jpg", gallery_urls=[f"{S3}/a.jpg"])
        self.assertEqual(stored_files(before) - stored_files(after),
                         {f"{S3}/thumb.jpg", f"{S3}/b.jpg"})

    def test_article_text_is_not_a_file(self):
        self.assertEqual(stored_files(post(content_url="# Notes\nhello")), set())


if __name__ == "__main__":
    unittest.main()
