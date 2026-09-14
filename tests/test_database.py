"""Business invariants, including concurrent booking and atomic rescheduling."""

import concurrent.futures
import tempfile
import unittest
from pathlib import Path

from lab_booking.database import BookingStore, ToolError


class BookingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = BookingStore(Path(self.tmp.name) / "lab.db")
        self.store.initialize()

    def tearDown(self):
        self.tmp.cleanup()

    def book(self, request_id="request-1", **changes):
        values = {"equipment": "M1", "date": "2026-10-05", "start": "11:00", "end": "12:00", **changes}
        return self.store.mutate("book", values, "alice", request_id)

    def test_preview_does_not_write(self):
        before = self.store.rows()
        self.store.prepare("book", {"equipment": "Microscope", "date": "2026-10-05", "start": "11:00", "end": "12:00"}, "alice")
        self.assertEqual(before, self.store.rows())

    def test_adjacent_booking_and_idempotent_retry(self):
        first = self.book()
        again = self.book()
        self.assertEqual(first["booking"]["id"], again["booking"]["id"])
        self.assertEqual(3, len(self.store.rows()))

    def test_overlap_rejected(self):
        before = self.store.rows()
        with self.assertRaises(ToolError) as error:
            self.book(start="10:30", end="11:30")
        self.assertEqual("conflict", error.exception.code)
        self.assertEqual(before, self.store.rows())

    def test_only_owner_can_cancel(self):
        with self.assertRaises(ToolError) as error:
            self.store.mutate("cancel", {"booking_id": "B0001"}, "alice", "cancel-bob")
        self.assertEqual("not_owned_or_missing", error.exception.code)
        self.assertEqual("active", self.store.rows()[0]["status"])

    def test_cancel_releases_slot(self):
        self.store.mutate("cancel", {"booking_id": "B0002"}, "alice", "cancel-own")
        result = self.book(equipment="C1", start="13:00", end="14:00")
        self.assertTrue(result["ok"])

    def test_failed_move_preserves_old_booking(self):
        self.book(equipment="C1", start="11:00", end="12:00")
        before = self.store.rows()
        with self.assertRaises(ToolError):
            self.store.mutate("reschedule", {"booking_id": "B0002", "date": "2026-10-05", "start": "11:00", "end": "12:00"}, "alice", "move-conflict")
        self.assertEqual(before, self.store.rows())

    def test_successful_move(self):
        result = self.store.mutate("reschedule", {"booking_id": "B0002", "date": "2026-10-05", "start": "14:00", "end": "15:00"}, "alice", "move-own")
        self.assertEqual("14:00", result["booking"]["start"])
        self.assertEqual(2, len(self.store.rows()))

    def test_validation(self):
        for changes, code in [
            ({"date": "2026-10-10"}, "closed_day"),
            ({"date": "2026-02-30"}, "invalid_date"),
            ({"start": "08:00", "end": "09:00"}, "outside_hours"),
            ({"start": "11:15"}, "invalid_time"),
            ({"start": "12:00", "end": "15:00"}, "duration_limit"),
            ({"equipment": "laser"}, "unknown_equipment"),
        ]:
            with self.subTest(changes=changes), self.assertRaises(ToolError) as error:
                self.book(**changes)
            self.assertEqual(code, error.exception.code)

    def test_sql_text_is_not_executed(self):
        with self.assertRaises(ToolError):
            self.store.mutate("cancel", {"booking_id": "B0002' OR 1=1 --"}, "alice", "sql-input")
        self.assertTrue(all(row["status"] == "active" for row in self.store.rows()))

    def test_concurrent_overlaps_allow_one_winner(self):
        def attempt(number):
            try:
                self.book(request_id=f"concurrent-{number}")
                return "success"
            except ToolError as error:
                return error.code
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(attempt, [1, 2]))
        self.assertCountEqual(["success", "conflict"], outcomes)
        self.assertEqual(3, len(self.store.rows()))


if __name__ == "__main__":
    unittest.main()
