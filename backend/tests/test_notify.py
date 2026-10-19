import os
import unittest
from unittest import mock

import httpx

from app.lib import notify

ENV = {"RESEND_API_KEY": "re_test", "SHOP_NOTIFY_EMAIL": "owner@example.com", "SHOP_PUBLIC_URL": "https://site.test"}


class NotifyTests(unittest.TestCase):
    def test_off_when_not_configured(self):
        with mock.patch.dict(os.environ, {"RESEND_API_KEY": "", "SHOP_NOTIFY_EMAIL": ""}), \
             mock.patch.object(notify.httpx, "post") as post:
            notify.new_offer("Lamp", 1, 3000, 4000, None, "b@x.co", None, None)
        post.assert_not_called()

    def test_offer_email(self):
        with mock.patch.dict(os.environ, ENV), mock.patch.object(notify.httpx, "post") as post:
            post.return_value = mock.Mock(status_code=200)
            notify.new_offer("Lamp <b>", 2, 3000, 4000, "Sam", "b@x.co", "555", "sat?")
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["to"], ["owner@example.com"])
        self.assertEqual(payload["reply_to"], "b@x.co")
        self.assertEqual(payload["subject"], "Offer: $30.00 for Lamp <b>")
        self.assertIn("Lamp &lt;b&gt; × 2", payload["html"])  # escaped
        self.assertIn("$30.00 (listed $40.00) each", payload["text"])
        self.assertIn("https://site.test/admin", payload["text"])

    def test_request_at_listed_price(self):
        with mock.patch.dict(os.environ, ENV), mock.patch.object(notify.httpx, "post") as post:
            post.return_value = mock.Mock(status_code=200)
            notify.new_offer("Lamp", 1, None, 4000, None, "b@x.co", None, None)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["subject"], "Pay-in-person request: Lamp")
        self.assertNotIn("Phone", payload["text"])  # blank fields are left out

    def test_test_mode_purchase_is_marked(self):
        with mock.patch.dict(os.environ, ENV), mock.patch.object(notify.httpx, "post") as post:
            post.return_value = mock.Mock(status_code=200)
            notify.meetup_paid("Lamp", 1, 4000, "b@x.co", "555", livemode=False)
        self.assertTrue(post.call_args.kwargs["json"]["subject"].startswith("[TEST] Paid online"))

    def test_failures_never_raise(self):
        with mock.patch.dict(os.environ, ENV), \
             mock.patch.object(notify.httpx, "post", side_effect=httpx.ConnectError("down")):
            notify.meetup_paid("Lamp", 1, 4000, "b@x.co", None, livemode=True)


if __name__ == "__main__":
    unittest.main()
