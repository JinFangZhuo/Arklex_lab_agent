"""Review and convert an upstream generator draft to the current runtime schema.

Task names/intents come from the recorded generator. Phase templates and resource
bindings are explicitly authored: this is not an automatic semantic compiler.
"""
import hashlib
import json
from pathlib import Path

from . import ROOT

MAPPING = {
    "task_1": "list_equipment", "task_2": "availability", "task_3": "book",
    "task_4": "list_bookings", "task_5": "reschedule", "task_6": "cancel", "task_7": "policy",
}
EXPECTED_NAMES = [
    "List available laboratory equipment", "Check availability of specific equipment",
    "Create a reservation for a specific equipment", "List own reservations",
    "Reschedule an existing reservation", "Cancel an existing reservation", "Understand booking rules",
]
WRITES = {"book", "reschedule", "cancel"}


def compile_graph(directory=ROOT / "generation", output=ROOT / "taskgraph.json"):
    directory = Path(directory)
    tasks = json.loads((directory / "tasks.raw.json").read_text())
    if [task["name"] for task in tasks] != EXPECTED_NAMES:
        raise ValueError("The regenerated task list changed. Review MAPPING and EXPECTED_NAMES before compiling.")
    nodes, edges = [], []

    def node(key, worker, action="", phase="", **data):
        nodes.append([key, {"resource": {"id": worker},
                           "attribute": {"start": key == "agent", "can_skipped": False, "limit": 1},
                           "data": {"action": action, "phase": phase, **data}}])

    def edge(a, b, intent="none", definition="", examples=None, global_intent=False):
        edges.append([a, b, {"intent": intent, "attribute": {"weight": 1, "pred": global_intent,
                          "definition": definition, "sample_utterances": examples or []}}])

    node("agent", "nlu-agent", prompt="Laboratory equipment reservations. Use the user's latest request and verified database results.", language="EN", response_length=350)
    node("welcome", "lab-welcome", phase="welcome")
    edge("agent", "welcome")
    review = []
    for task in tasks:
        action = MAPPING[task["id"]]
        first = action + (".collect" if action in WRITES or action == "availability" else ".query")
        edge("welcome", first, task["intent"], task["description"], global_intent=True)
        if action in WRITES:
            node(first, "lab-collect", action, "collect")
            node(action + ".confirm", "lab-confirm", action, "confirm")
            node(action + ".commit", "lab-commit", action, "commit")
            node(action + ".discard", "lab-discard", action, "discard")
            edge(first, action + ".confirm")
            edge(action + ".confirm", action + ".commit", "Approve the displayed request",
                 "User unconditionally approves exactly the previously displayed request, without changing fields or adding conditions.", ["Confirm.", "Yes, go ahead."])
            edge(action + ".confirm", first, "Correct the pending request",
                 "User supplies or changes equipment, date, time, duration or booking ID for this pending request; an affirmative with corrections belongs here.", ["Use 15:30 to 16:30 instead.", "Yes, but change the date."])
            edge(action + ".confirm", action + ".discard", "Abandon the pending request",
                 "User declines or abandons this pending change. This is not a request to cancel an existing booking.", ["Never mind.", "Do not proceed."])
        elif action == "availability":
            node(first, "lab-query", action, "query")
        else:
            node(first, "lab-query", action, "query")
        review.append({"generated_task_id": task["id"], "name": task["name"], "intent": task["intent"],
                       "runtime_action": action, "entry_node": first,
                       "raw_steps": len(task["steps"]), "decision": "Keep task and intent; replace steps and resource assignments with reviewed phase template."})
    workers = sorted({n[1]["resource"]["id"] for n in nodes} - {"nlu-agent"}) + ["planner"]
    graph = {"name": "LabBook", "nodes": nodes, "edges": edges, "workers": [{"id": w} for w in workers], "tools": [], "agents": []}
    Path(output).write_text(json.dumps(graph, indent=2) + "\n")
    report = {"reviewer": "AI-assisted implementation review",
              "raw_graph_sha256": hashlib.sha256((directory / "taskgraph.raw.json").read_bytes()).hexdigest(),
              "runtime_graph_sha256": hashlib.sha256(Path(output).read_bytes()).hexdigest(),
              "issues": ["Generator emits an older node schema (type=start, attribute.value); runtime requires an agent root and data fields.",
                         "Resource assignment uses round-robin indexing in the pinned BestPracticeManager, not semantic matching.",
                         "The generated creation flow places a creation step before an explicit proceed question.",
                         "Single-step fallback tasks omit collection, validation and confirmation."],
              "changes": ["Use current runtime schema.", "Bind deterministic read tools to query nodes.",
                          "Use collect -> display -> local approval/correction/discard edges for each write.",
                          "Add an explicit fallback Worker at resource ID planner.", "Enforce transactional invariants and optional application confirmation guard."],
              "task_mapping": review, "node_count": len(nodes), "edge_count": len(edges)}
    (directory / "review.json").write_text(json.dumps(report, indent=2) + "\n")
    return graph


if __name__ == "__main__":
    compile_graph()
