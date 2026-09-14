"""Behavioral tests at the write boundary, independent of NLU predictions."""
import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from lab_booking.database import BookingStore, ToolError
from lab_booking.worker import Session, LabCommitWorker, fingerprint, explicit_confirmation


class AuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = BookingStore(Path(self.tmp.name) / "db.sqlite")
        self.store.initialize()
        self.session = Session(self.store, None, "alice")
        self.session.pending = {"action":"book","arguments":{"equipment":"M1","date":"2026-10-06","start":"09:00","end":"10:00"},"revision":1,"request_id":"test-request"}
        self.session.shown_fingerprint = fingerprint(self.session.pending)
        self.session.shown_turn, self.session.turn = 1, 2

    def tearDown(self):
        self.tmp.cleanup()

    def commit(self, message):
        worker = LabCommitWorker()
        worker.init_worker_data(SimpleNamespace(user_message=SimpleNamespace(message=message)), {"session":self.session,"action":"book","phase":"commit"})
        return worker.run()[0]

    def test_unconditional_confirm_writes_once(self):
        self.assertEqual("book_success",self.commit("Confirm.")["code"])
        with self.assertRaises(ToolError):
            self.commit("Confirm.")
        self.assertEqual(3,len(self.store.rows()))

    def test_misrouted_correction_cannot_write(self):
        before = self.store.rows()
        self.assertEqual("confirmation_not_explicit",self.commit("Yes, but change it to 11:00.")["code"])
        self.assertEqual(before,self.store.rows())

    def test_mutated_snapshot_cannot_be_confirmed(self):
        self.session.pending["arguments"]["start"] = "09:30"
        with self.assertRaises(ToolError) as error:
            self.commit("Confirm.")
        self.assertEqual("stale_confirmation",error.exception.code)
        self.assertEqual(2,len(self.store.rows()))

    def test_no_same_turn_approval(self):
        self.session.turn = self.session.shown_turn
        with self.assertRaises(ToolError):
            self.commit("Confirm.")

    def test_graph_only_ablation_removes_only_grammar(self):
        self.session.variant = "graph_only"
        self.assertEqual("book_success",self.commit("Yes, but only after my supervisor approves.")["code"])

    def test_affirmation_grammar(self):
        for message in ["Confirm.","Yes, go ahead.","确认预约", "OK please"]:
            self.assertTrue(explicit_confirmation(message), message)
        for message in ["Don't confirm",'She said "confirm".',"Yes, but tomorrow", "Confirm if approved", "yes; DROP TABLE bookings"]:
            self.assertFalse(explicit_confirmation(message), message)


if __name__ == "__main__":
    unittest.main()
