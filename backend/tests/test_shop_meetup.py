import unittest
from unittest import mock

from app.routes import shop_meetup


class RateLimitTests(unittest.TestCase):
    def setUp(self):
        shop_meetup._recent.clear()

    def test_allows_a_handful_then_blocks(self):
        for _ in range(shop_meetup.RATE_LIMIT):
            self.assertTrue(shop_meetup._allow("1.2.3.4"))
        self.assertFalse(shop_meetup._allow("1.2.3.4"))
        self.assertTrue(shop_meetup._allow("5.6.7.8"))  # per visitor

    def test_window_slides(self):
        with mock.patch.object(shop_meetup.time, "monotonic", return_value=1000.0):
            for _ in range(shop_meetup.RATE_LIMIT):
                shop_meetup._allow("1.2.3.4")
        later = 1000.0 + shop_meetup.RATE_WINDOW_S + 1
        with mock.patch.object(shop_meetup.time, "monotonic", return_value=later):
            self.assertTrue(shop_meetup._allow("1.2.3.4"))


class EmailCheckTests(unittest.TestCase):
    def test_email_shape(self):
        self.assertTrue(shop_meetup.EMAIL_RE.match("a@b.co"))
        self.assertFalse(shop_meetup.EMAIL_RE.match("not an email"))
        self.assertFalse(shop_meetup.EMAIL_RE.match("a@b"))


if __name__ == "__main__":
    unittest.main()
