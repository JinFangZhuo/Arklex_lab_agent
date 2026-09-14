# Qualitative audit of the revised simulator

This is an AI-assisted review of the recorded v2 trajectories, performed after execution. It is not a blinded human annotation study. Database goal completion and simulator quality are different measurements; an episode can satisfy one and fail the other.

| Episode | Goal reached | Behavior observed | Interpretation |
| --- | --- | --- | --- |
| direct-booker | No | Initial request includes “Confirm only the correct details”; extraction rejects it. The simulator then repeatedly says “Confirm” without a displayed proposal. | A plausible initial compound request exposes an extraction weakness, followed by simulator noncompliance and a recovery loop. |
| incremental-booker | Yes | Supplies all fields initially despite its incremental style; continues confirming after success. | Correct database result, weak style and stopping fidelity. |
| colloquial-booker | Yes | Uses am/pm and a numeric date successfully; later speaks as the assistant. | Useful initial paraphrase, role drift after completion. |
| careful-booker | Yes | Asks for available times rather than the assigned preliminary opening-hours question; the agent displays a booking and the user confirms. | Final goal reached, but the requested scenario style is not followed. |
| direct-canceller | Yes | Cancels correctly, then continues sending confirmations. | Correct result with poor stopping behavior. |
| careful-canceller | Yes | Lists bookings, requests cancellation, confirms, and stops. | Best adherence to the assigned multi-step scenario in this small run. |
| direct-rescheduler | No | Adds “Confirm” to its initial move request; extraction rejects it, followed by repeated premature confirmation. | Shared extraction and simulator recovery failure. |
| incremental-rescheduler | No | Adds premature confirmation and later invents equipment Z10, outside its assigned goal. | Simulator goal drift prevents a clean attribution to agent task capability. |

The **5/8** figure describes final goal states under this particular simulator, not success with five independently validated realistic users. No empty-message/transport error was detected in v2, but that does not establish behavioral validity. A future evaluator needs separate role, goal-consistency, confirmation-timing, and stopping checks, with human spot checks and a different simulator model family.

The v1 pilot and v2 redesign are both retained. Reusing the same eight goals after revising the simulator makes v2 development evidence. The agent and the frozen 24-scenario benchmark were not tuned in response to these simulation results.
