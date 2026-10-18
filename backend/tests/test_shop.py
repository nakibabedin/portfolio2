import hashlib
import hmac
import json
import time
import unittest

import stripe

from app.lib import printify

PRODUCT = {
    "id": "prod1",
    "title": "Tee",
    "blueprint_id": 6,
    "print_provider_id": 99,
    "options": [
        {"name": "Colors", "type": "color", "values": [
            {"id": 1, "title": "Black", "colors": ["#000000"]},
            {"id": 2, "title": "White", "colors": ["#ffffff"]},
        ]},
        {"name": "Sizes", "type": "size", "values": [
            {"id": 10, "title": "S"},
            {"id": 11, "title": "M"},
            {"id": 12, "title": "2XL"},
        ]},
    ],
    "variants": [
        {"id": 100, "title": "Black / S", "price": 2500, "cost": 1200, "options": [1, 10], "is_enabled": True, "is_available": True},
        {"id": 101, "title": "Black / M", "price": 2500, "cost": 1200, "options": [1, 11], "is_enabled": True, "is_available": True},
        {"id": 102, "title": "Black / 2XL", "price": 2900, "cost": 1500, "options": [1, 12], "is_enabled": True, "is_available": False},
        {"id": 103, "title": "White / S", "price": 2000, "cost": 1200, "options": [2, 10], "is_enabled": False, "is_available": True},
    ],
    "images": [
        {"src": "https://img/back.png", "variant_ids": [100, 101], "is_default": False},
        {"src": "https://img/front.png", "variant_ids": [100, 101], "is_default": True},
    ],
}

class PrintifyHelperTests(unittest.TestCase):
    def test_only_enabled_in_stock_variants_are_sellable(self):
        self.assertEqual([v["id"] for v in printify.sellable_variants(PRODUCT)], [100, 101])
        self.assertIsNone(printify.find_sellable_variant(PRODUCT, 102))  # out of stock
        self.assertIsNone(printify.find_sellable_variant(PRODUCT, 103))  # disabled
        self.assertEqual(printify.min_price_cents(PRODUCT), 2500)

    def test_public_listing_hides_unsellable_options_and_costs(self):
        listing = printify.listing(PRODUCT, 535)
        values = {o["name"]: [v["title"] for v in o["values"]] for o in listing["options"]}
        self.assertEqual(values, {"Colors": ["Black"], "Sizes": ["S", "M"]})
        self.assertNotIn("cost_cents", listing["variants"][0])
        self.assertEqual(listing["shipping_cents"], 535)

    def test_admin_listing_keeps_every_variant_with_cost(self):
        listing = printify.listing(PRODUCT, None, include_costs=True)
        self.assertEqual(len(listing["variants"]), 4)
        self.assertEqual(listing["variants"][2]["cost_cents"], 1500)
        self.assertFalse(listing["variants"][3]["is_enabled"])

    def test_variant_image_prefers_default_mockup(self):
        self.assertEqual(printify.variant_image(PRODUCT, 100), "https://img/front.png")

    def test_address_from_new_and_old_session_shapes(self):
        address = {"line1": "1 Main St", "line2": None, "city": "Austin", "state": "TX", "postal_code": "78701", "country": "US"}
        customer = {"email": "a@b.co", "phone": "+15125550100", "name": "Billing Name"}
        new = {"collected_information": {"shipping_details": {"name": "Jane Q Doe", "address": address}}, "customer_details": customer}
        old = {"shipping_details": {"name": "Jane Q Doe", "address": address}, "customer_details": customer}
        for session in (new, old):
            out = printify.address_to(session)
            self.assertEqual((out["first_name"], out["last_name"]), ("Jane", "Q Doe"))
            self.assertEqual((out["region"], out["zip"], out["address2"]), ("TX", "78701", ""))
            self.assertEqual(out["email"], "a@b.co")

    def test_webhook_signature(self):
        body = b'{"type":"order:updated"}'
        good = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
        self.assertTrue(printify.verify_webhook_signature(body, good, "s3cret"))
        self.assertFalse(printify.verify_webhook_signature(body, good, "other"))
        self.assertFalse(printify.verify_webhook_signature(body, None, "s3cret"))
        self.assertFalse(printify.verify_webhook_signature(body, good, ""))


class StripeEventTests(unittest.TestCase):
    def test_signed_event_round_trips_to_dict(self):
        """The webhook reads the session via ``event.data.object.to_dict()``."""
        secret = "whsec_test"
        payload = json.dumps({
            "id": "evt_1", "object": "event", "type": "checkout.session.completed", "livemode": False,
            "data": {"object": {"id": "cs_1", "object": "checkout.session", "payment_status": "paid",
                                "collected_information": {"shipping_details": {"name": "A B", "address": {"country": "US"}}}}},
        })
        ts = int(time.time())
        sig = hmac.new(secret.encode(), f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()
        event = stripe.Webhook.construct_event(payload, f"t={ts},v1={sig}", secret)
        session = event.data.object.to_dict()
        self.assertEqual(event.type, "checkout.session.completed")
        self.assertEqual(session["payment_status"], "paid")
        self.assertEqual(printify.address_to(session)["country"], "US")
        with self.assertRaises(stripe.SignatureVerificationError):
            stripe.Webhook.construct_event(payload, f"t={ts},v1={sig}", "whsec_wrong")


if __name__ == "__main__":
    unittest.main()
