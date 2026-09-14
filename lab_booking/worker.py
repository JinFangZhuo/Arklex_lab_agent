"""Small custom Workers; Arklex's native NLUGraph chooses every task and phase."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field

from arklex.orchestrator.entities.orchestrator_state_entities import StatusEnum
from arklex.resources.workers.base.base_worker import BaseWorker
from arklex.resources.workers.base.entities import WorkerOutput

from .database import BookingStore, ToolError
from .model import ModelClient


def explicit_confirmation(message):
    normalized = " ".join(re.sub(r"[.!。,，！]+", " ", message.casefold()).split())
    grammar = (r"(?:(?:yes|ok|okay) )?(?:please )?"
               r"(?:confirm(?: (?:it|the (?:booking|reservation|cancellation|reschedule|request)))?|go ahead|proceed)"
               r"(?: please)?|(?:yes|ok|okay)(?: please)?|确认(?:预约|取消|改期|执行)?|好的|是的")
    return re.fullmatch(f"(?:{grammar})", normalized) is not None


def fingerprint(pending):
    return hashlib.sha256(json.dumps({k: pending[k] for k in ("action", "arguments", "revision", "request_id")}, sort_keys=True).encode()).hexdigest()


@dataclass
class Session:
    store: BookingStore
    model: ModelClient
    user_id: str
    variant: str = "guarded"
    pending: dict | None = None
    shown_fingerprint: str | None = None
    shown_turn: int = -1
    turn: int = 0
    revision: int = 0
    recent_booking_id: str | None = None
    last_result: dict = field(default_factory=dict)
    events: list = field(default_factory=list)


class LabOutput(WorkerOutput):
    response: str = ""
    status: StatusEnum = StatusEnum.COMPLETE


def render(result):
    code = result["code"]
    if not result.get("ok"):
        return result["message"]
    if code == "welcome":
        return "Hello! I can list lab equipment, check availability, and manage your reservations. This is a synthetic lab; all times are America/New_York."
    if code == "confirmation_required":
        request = result["request"]
        detail = ", ".join(f"{k}={v}" for k, v in request["arguments"].items())
        return f"Please confirm {request['action']}: {detail} (America/New_York). Reply 'confirm' to proceed, 'never mind' to discard, or provide corrections. No change has been made yet."
    if "booking" in result:
        row = result["booking"]
        label = {"book_success": "Booked", "cancel_success": "Cancelled", "reschedule_success": "Rescheduled", "replayed": "Already processed"}[code]
        return f"{label}: {row['id']}, {row['equipment_id']}, {row['date']} {row['start']}–{row['end']} America/New_York. Status: {row['status']}."
    if code == "list_equipment":
        return "Equipment: " + "; ".join(f"{r['id']} {r['name']} ({r['description']})" for r in result["equipment"]) + "."
    if code == "list_bookings":
        return "Your active bookings: " + ("; ".join(f"{r['id']}: {r['equipment_id']} {r['date']} {r['start']}–{r['end']}" for r in result["bookings"]) or "none") + " (America/New_York)."
    if code == "availability":
        return f"Available half-hour slots for {result['equipment']} on {result['date']}: " + ", ".join(f"{s['start']}–{s['end']}" for s in result["available_half_hour_slots"]) + " (America/New_York)."
    if code == "policy":
        return "Lab hours: Monday–Friday, 09:00–17:00 America/New_York. Use 30-minute boundaries; maximum duration is 120 minutes. Confirm changes before execution. You may change only your own bookings."
    if code == "aborted":
        return "The pending request has been discarded. No booking was changed."
    raise ValueError(code)


class LabWorker(BaseWorker):
    def init_worker_data(self, orch_state, node_specific_data):
        self.orch_state = orch_state
        self.session = node_specific_data["session"]
        self.action = node_specific_data.get("action", "")
        self.phase = node_specific_data.get("phase", "fallback")
        self.message = orch_state.user_message.message

    def _execute(self):
        session = self.session
        try:
            result, complete, speak = self.run()
        except ToolError as error:
            result = {"ok": False, "code": error.code, "message": str(error), **error.data}
            complete, speak = False, True
        except Exception as error:
            # Fail closed on transport/extraction errors. Preserve type for diagnosis.
            result = {"ok": False, "code": "worker_error", "error_type": type(error).__name__,
                      "message": "I could not process that request reliably. No change was made by this step; please rephrase."}
            complete, speak = False, True
        session.last_result = result
        session.events.append({"action": self.action, "phase": self.phase, "result": copy.deepcopy(result)})
        return LabOutput(response=render(result) if speak else "", status=StatusEnum.COMPLETE if complete else StatusEnum.INCOMPLETE)

    def extract(self):
        s = self.session
        command = s.model.extract(self.message, s.pending, s.recent_booking_id).model_dump()
        s.events.append({"phase": "extract", "command": command})
        if command["action"] in {"unknown", "abort", "confirm"}:
            raise ToolError("unsupported_details", "Please state the booking details or a supported request. No booking was changed.")
        return {k: v for k, v in command.items() if k != "action" and v is not None}


class LabCollectWorker(LabWorker):
    description = "Collect and validate arguments for the task selected by Arklex. Never write."

    def run(self):
        s = self.session
        if not s.pending or s.pending["action"] != self.action:
            s.pending = {"action": self.action, "arguments": {}, "revision": s.revision, "request_id": uuid.uuid4().hex}
        s.shown_fingerprint = None
        s.pending["arguments"].update(self.extract())
        values = s.store.prepare(self.action, s.pending["arguments"], s.user_id)
        s.revision += 1
        s.pending.update(arguments=values, revision=s.revision, request_id=uuid.uuid4().hex)
        return {"ok": True, "code": "validated"}, True, False


class LabConfirmWorker(LabWorker):
    description = "Display a validated request and bind its exact revision to a later confirmation."

    def run(self):
        s = self.session
        if not s.pending or s.pending["action"] != self.action:
            raise ToolError("nothing_to_confirm", "There is no complete request to confirm.")
        # Even an unexpected graph transition must not display an incomplete request.
        s.pending["arguments"] = s.store.prepare(self.action, s.pending["arguments"], s.user_id)
        s.shown_fingerprint, s.shown_turn = fingerprint(s.pending), s.turn
        return {"ok": True, "code": "confirmation_required", "request": copy.deepcopy(s.pending)}, True, True


class LabCommitWorker(LabWorker):
    description = "Commit only a displayed request, with optional deterministic confirmation guard."

    def run(self):
        s = self.session
        if not s.pending or s.pending["action"] != self.action or s.shown_fingerprint != fingerprint(s.pending) or s.shown_turn >= s.turn:
            raise ToolError("stale_confirmation", "Please state the request again so I can show its current details before execution.")
        if s.variant == "guarded" and not explicit_confirmation(self.message):
            # Return COMPLETE so a rejected local route does not trap the commit node.
            return {"ok": False, "code": "confirmation_not_explicit", "message": "No change was made. Please restate the request and confirm the displayed details without conditions."}, True, True
        result = s.store.mutate(self.action, s.pending["arguments"], s.user_id, s.pending["request_id"])
        s.recent_booking_id = result["booking"]["id"]
        s.pending, s.shown_fingerprint = None, None
        return result, True, True


class LabQueryWorker(LabWorker):
    description = "Read equipment, availability, own reservations, or booking policy."

    def run(self):
        s = self.session
        if self.action == "availability":
            if not s.pending or s.pending["action"] != self.action:
                s.pending = {"action": self.action, "arguments": {}}
            s.pending["arguments"].update(self.extract())
            result = s.store.query(self.action, s.pending["arguments"], s.user_id)
        else:
            result = s.store.query(self.action, {}, s.user_id)
        # Switching to a read task discards any uncommitted write.
        s.pending, s.shown_fingerprint = None, None
        return result, True, True


class LabDiscardWorker(LabWorker):
    def run(self):
        self.session.pending, self.session.shown_fingerprint = None, None
        return {"ok": True, "code": "aborted"}, True, True


class LabWelcomeWorker(LabWorker):
    def run(self):
        return {"ok": True, "code": "welcome"}, True, True


class LabFallbackWorker(LabWorker):
    def run(self):
        return {"ok": False, "code": "unsupported_request", "message": "I can list equipment, check availability, manage your own reservations, or explain lab rules. Please state the operation and details."}, True, True


WORKERS = {"lab-collect": LabCollectWorker, "lab-confirm": LabConfirmWorker, "lab-commit": LabCommitWorker,
           "lab-query": LabQueryWorker, "lab-discard": LabDiscardWorker, "lab-welcome": LabWelcomeWorker, "planner": LabFallbackWorker}
