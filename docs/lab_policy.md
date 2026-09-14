# LabBook policy and fixture domain

LabBook is a simulated laboratory front desk. All bookings exist only in a local SQLite database.

- Equipment: M1 Microscope, C1 Centrifuge, P1 PCR machine. Each has capacity one.
- Time zone: America/New_York. Opening hours: weekdays 09:00–17:00.
- Start/end times must use 30-minute boundaries. Duration must be positive and at most two hours.
- Use explicit calendar dates. Ask for clarification when date or time is ambiguous.
- Ask for explicit confirmation after showing a complete write request. Changes to a request require a new confirmation.
- Availability may change between proposal and confirmation. Recheck it transactionally when committing.
- Only the authenticated user can change their own bookings. User identity is application context, not an LLM argument.
- An unsuccessful reschedule leaves the original booking active and unchanged.
- The seed database contains Bob's M1 booking on 2026-10-05 10:00–11:00 (B0001) and Alice's C1 booking on 2026-10-05 13:00–14:00 (B0002).
- Dates are explicit fixture dates for reproducible evaluation. No live institutional schedule is connected.

The assistant supports English and basic Chinese equipment names. Language coverage must be assessed from the evaluation rather than assumed.
