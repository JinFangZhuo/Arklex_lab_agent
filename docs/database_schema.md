# Database tools

`equipment(id, name, description, max_minutes)` stores the synthetic catalog.

`bookings(id, equipment_id, date, start, end, user_id, status, request_id)` stores reservations, including cancelled rows for audit.

`operations(request_id, user_id, action, booking_id)` records committed mutations. Repeating a committed operation ID returns the prior booking without creating a second reservation.

Tool functions: `query` (catalog, policy, availability, own bookings), `prepare` (validate a proposed mutation without writing), and `mutate` (create, cancel, reschedule under `BEGIN IMMEDIATE`). All SQL values are parameterized. Conflict detection excludes cancelled reservations and, when moving a reservation, excludes the reservation itself.

Evaluation reads the final tables independently of the assistant's statements.
