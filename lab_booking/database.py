"""Transactional tools. The authenticated user comes from the app, never the LLM."""

from __future__ import annotations

import contextlib
import datetime as dt
import sqlite3
import uuid
from pathlib import Path

CATALOG = [
    ("M1", "Microscope", "Fluorescence imaging", 120),
    ("C1", "Centrifuge", "Sample separation", 120),
    ("P1", "PCR machine", "DNA amplification", 120),
]
ALIASES = {
    "m1": "M1", "microscope": "M1", "fluorescence microscope": "M1", "显微镜": "M1",
    "c1": "C1", "centrifuge": "C1", "离心机": "C1",
    "p1": "P1", "pcr": "P1", "pcr machine": "P1", "pcr仪": "P1",
}
POLICY = {
    "timezone": "America/New_York",
    "opening_time": "09:00",
    "closing_time": "17:00",
    "max_duration_minutes": 120,
    "time_step_minutes": 30,
    "booking_days": "Monday to Friday",
    "confirmation": "Explicit confirmation is required before creating, moving or cancelling a booking.",
    "ownership": "Only the authenticated user's bookings can be changed.",
    "environment": "Synthetic local lab; no external calendar or real reservation is modified.",
}


class ToolError(Exception):
    def __init__(self, code: str, message: str, **data):
        super().__init__(message)
        self.code, self.data = code, data


class BookingStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    @contextlib.contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self):
        """Create a fixture database; refuse to overwrite an existing file."""
        if self.path.exists():
            raise FileExistsError(f"Database already exists: {self.path}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript("""
                CREATE TABLE equipment (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    description TEXT NOT NULL, max_minutes INTEGER NOT NULL
                );
                CREATE TABLE bookings (
                    id TEXT PRIMARY KEY, equipment_id TEXT NOT NULL REFERENCES equipment(id),
                    date TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL,
                    user_id TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('active','cancelled')),
                    request_id TEXT UNIQUE NOT NULL, CHECK(start < end)
                );
                CREATE TABLE operations (
                    request_id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                    action TEXT NOT NULL, booking_id TEXT NOT NULL REFERENCES bookings(id)
                );
            """)
            connection.executemany("INSERT INTO equipment VALUES (?,?,?,?)", CATALOG)
            connection.executemany("INSERT INTO bookings VALUES (?,?,?,?,?,?,?,?)", [
                ("B0001", "M1", "2026-10-05", "10:00", "11:00", "bob", "active", "fixture-bob"),
                ("B0002", "C1", "2026-10-05", "13:00", "14:00", "alice", "active", "fixture-alice"),
            ])
            connection.commit()

    def rows(self):
        with self.connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM bookings ORDER BY id")]

    @staticmethod
    def equipment(value):
        if not value:
            raise ToolError("missing_fields", "Please specify the equipment.", fields=["equipment"])
        normalized = ALIASES.get(str(value).strip().lower())
        if not normalized:
            raise ToolError("unknown_equipment", "Choose M1 (Microscope), C1 (Centrifuge), or P1 (PCR machine).")
        return normalized

    @staticmethod
    def date(value):
        try:
            parsed = dt.date.fromisoformat(value)
            if value != parsed.isoformat():
                raise ValueError
        except (TypeError, ValueError):
            raise ToolError("invalid_date", "Please provide a real date in YYYY-MM-DD format.")
        if parsed.weekday() > 4:
            raise ToolError("closed_day", "The laboratory is closed on weekends.")
        return value

    @staticmethod
    def time(value):
        try:
            parsed = dt.time.fromisoformat(value)
            if value != parsed.strftime("%H:%M") or parsed.minute not in (0, 30):
                raise ValueError
        except (TypeError, ValueError):
            raise ToolError("invalid_time", "Use HH:MM with 30-minute boundaries, for example 09:30.")
        return parsed.hour * 60 + parsed.minute

    def interval(self, date, start, end):
        self.date(date)
        begin, finish = self.time(start), self.time(end)
        if not (9 * 60 <= begin < finish <= 17 * 60):
            raise ToolError("outside_hours", "Bookings must start before they end, within 09:00–17:00.")
        if finish - begin > 120:
            raise ToolError("duration_limit", "A booking may last at most 120 minutes.")

    @staticmethod
    def owned(connection, booking_id, user_id):
        row = connection.execute("SELECT * FROM bookings WHERE id=? AND user_id=?", (booking_id, user_id)).fetchone()
        if not row:
            raise ToolError("not_owned_or_missing", "No booking with that ID belongs to your account.")
        return dict(row)

    @staticmethod
    def conflict(connection, equipment, date, start, end, exclude=""):
        return connection.execute(
            "SELECT id FROM bookings WHERE equipment_id=? AND date=? AND status='active' "
            "AND start < ? AND end > ? AND id != ? LIMIT 1",
            (equipment, date, end, start, exclude),
        ).fetchone() is not None

    def prepare(self, action, arguments, user_id):
        """Validate and canonicalize a proposed write without changing the database."""
        values = dict(arguments)
        required = {
            "book": ["equipment", "date", "start", "end"],
            "cancel": ["booking_id"],
            "reschedule": ["booking_id", "date", "start", "end"],
        }.get(action)
        if required is None:
            raise ToolError("unknown_action", "Unsupported write operation.")
        missing = [field for field in required if not values.get(field)]
        if missing:
            raise ToolError("missing_fields", "Please provide: " + ", ".join(missing) + ".", fields=missing)
        with self.connect() as connection:
            if action in ("cancel", "reschedule"):
                old = self.owned(connection, values["booking_id"], user_id)
                if old["status"] != "active":
                    raise ToolError("already_cancelled", "That booking is already cancelled.")
                values["equipment"] = old["equipment_id"]
            else:
                values["equipment"] = self.equipment(values["equipment"])
            if action != "cancel":
                self.interval(values["date"], values["start"], values["end"])
                exclude = values.get("booking_id", "") if action == "reschedule" else ""
                if self.conflict(connection, values["equipment"], values["date"], values["start"], values["end"], exclude):
                    raise ToolError("conflict", "That time is occupied. Choose another time; no booking was changed.")
        return {key: values[key] for key in required + (["equipment"] if "equipment" not in required else [])}

    def mutate(self, action, values, user_id, request_id):
        """Recheck constraints under a write lock; make retries idempotent."""
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                previous = connection.execute("SELECT * FROM operations WHERE request_id=?", (request_id,)).fetchone()
                if previous:
                    if previous["user_id"] != user_id or previous["action"] != action:
                        raise ToolError("request_mismatch", "This operation ID belongs to a different request.")
                    row = self.owned(connection, previous["booking_id"], user_id)
                    connection.commit()
                    return {"ok": True, "code": "replayed", "booking": row}
                # Validates format/ownership; overlap is checked again on this locked connection.
                if action not in ("book", "cancel", "reschedule"):
                    raise ToolError("unknown_action", "Unsupported write operation.")
                if action in ("cancel", "reschedule"):
                    old = self.owned(connection, values["booking_id"], user_id)
                    if old["status"] != "active":
                        raise ToolError("already_cancelled", "That booking is already cancelled.")
                    equipment = old["equipment_id"]
                else:
                    equipment = self.equipment(values["equipment"])
                if action != "cancel":
                    self.interval(values["date"], values["start"], values["end"])
                    exclude = values["booking_id"] if action == "reschedule" else ""
                    if self.conflict(connection, equipment, values["date"], values["start"], values["end"], exclude):
                        raise ToolError("conflict", "That time is occupied. Choose another time; no booking was changed.")
                booking_id = values.get("booking_id") if action != "book" else "B" + uuid.uuid4().hex[:10].upper()
                if action == "book":
                    connection.execute("INSERT INTO bookings VALUES (?,?,?,?,?,?,?,?)", (
                        booking_id, equipment, values["date"], values["start"], values["end"], user_id, "active", request_id,
                    ))
                elif action == "cancel":
                    connection.execute("UPDATE bookings SET status='cancelled' WHERE id=? AND user_id=?", (booking_id, user_id))
                else:
                    connection.execute("UPDATE bookings SET date=?,start=?,end=? WHERE id=? AND user_id=?", (
                        values["date"], values["start"], values["end"], booking_id, user_id,
                    ))
                connection.execute("INSERT INTO operations VALUES (?,?,?,?)", (request_id, user_id, action, booking_id))
                row = self.owned(connection, booking_id, user_id)
                connection.commit()
                return {"ok": True, "code": action + "_success", "booking": row}
            except Exception:
                connection.rollback()
                raise

    def query(self, action, values, user_id):
        with self.connect() as connection:
            if action == "list_equipment":
                return {"ok": True, "code": action, "equipment": [dict(row) for row in connection.execute("SELECT * FROM equipment ORDER BY id")]}
            if action == "list_bookings":
                rows = connection.execute("SELECT * FROM bookings WHERE user_id=? AND status='active' ORDER BY date,start", (user_id,))
                return {"ok": True, "code": action, "bookings": [dict(row) for row in rows]}
            if action == "policy":
                return {"ok": True, "code": action, "policy": POLICY}
            if action == "availability":
                missing = [key for key in ("equipment", "date") if not values.get(key)]
                if missing:
                    raise ToolError("missing_fields", "Please provide: " + ", ".join(missing) + ".", fields=missing)
                equipment = self.equipment(values["equipment"])
                date = self.date(values["date"])
                slots = []
                for minute in range(9 * 60, 17 * 60, 30):
                    start, end = f"{minute // 60:02d}:{minute % 60:02d}", f"{(minute + 30) // 60:02d}:{(minute + 30) % 60:02d}"
                    if not self.conflict(connection, equipment, date, start, end):
                        slots.append({"start": start, "end": end})
                return {"ok": True, "code": action, "equipment": equipment, "date": date, "available_half_hour_slots": slots}
            raise ToolError("unknown_action", "I can list equipment, check availability, book, reschedule or cancel your bookings.")
