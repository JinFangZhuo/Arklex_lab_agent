"""Execution metadata must never become model-visible booking arguments."""
import json
import unittest

from lab_booking.model import ModelClient


class ContextTests(unittest.TestCase):
    def test_private_request_metadata_is_not_sent_to_model(self):
        client = ModelClient({"base_url": "http://127.0.0.1:18123/v1", "model": "test"})
        seen = []

        def capture(messages, **kwargs):
            seen.extend(messages)
            return json.dumps(dict(action="confirm", equipment=None, date=None,
                                   start=None, end=None, booking_id=None))

        client.call = capture
        pending = {"action": "cancel", "arguments": {"booking_id": "B0123", "internal_audit": "private-marker"},
                   "stage": "awaiting_confirmation", "request_id": "private-transaction-marker"}
        client.extract("Confirm.", pending, None)
        payload = json.dumps(seen)
        self.assertNotIn("private-transaction-marker", payload)
        self.assertNotIn("private-marker", payload)
        self.assertNotIn("request_id", payload)
        self.assertIn("B0123", payload)
        self.assertEqual("private-transaction-marker", pending["request_id"])


if __name__ == "__main__":
    unittest.main()
