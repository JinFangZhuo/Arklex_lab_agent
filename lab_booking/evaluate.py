"""Paired end-to-end evaluation. Oracles are never passed to the agent."""
import argparse
import asyncio
import datetime
import hashlib
import json
import tempfile
from pathlib import Path

from . import ROOT
from .app import LabBookApp
from .database import BookingStore


def final_matches(spec, initial, rows):
    mode = spec["mode"]
    if mode == "unchanged":
        return rows == initial
    if mode == "book":
        new = [r for r in rows if r["id"] not in {b["id"] for b in initial}]
        return len(new) == 1 and new[0]["user_id"] == "alice" and new[0]["status"] == "active" and all(new[0].get(k) == v for k,v in spec.items() if k != "mode") and all(r in rows for r in initial)
    target = next((r for r in rows if r["id"] == spec["booking_id"]), None)
    unchanged_others = [r for r in rows if r["id"] != spec["booking_id"]] == [r for r in initial if r["id"] != spec["booking_id"]]
    if mode == "cancel":
        return bool(target and target["status"] == "cancelled" and unchanged_others)
    return bool(target and unchanged_others and target["status"] == "active" and all(target.get(k) == v for k,v in spec.items() if k not in {"mode","booking_id"}))


def code_digest():
    paths = sorted((ROOT / "lab_booking").glob("*.py")) + [ROOT / "taskgraph.json", ROOT / "config.json"]
    paths += sorted((ROOT / "patches").glob("*.patch"))
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


async def evaluate(args):
    path = ROOT / "evaluation/frozen_cases.json"
    manifest = json.loads((ROOT / "evaluation/freeze_manifest.json").read_text())
    if hashlib.sha256(path.read_bytes()).hexdigest() != manifest["sha256"]:
        raise ValueError("Frozen case checksum mismatch")
    cases = json.loads(path.read_text())
    destination = Path(args.output)
    destination.mkdir(parents=True, exist_ok=True)
    if (destination / "summary.json").exists():
        raise FileExistsError("Use a new output directory to retain prior evidence.")
    evidence = {"started_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(), "corpus":manifest, "code_sha256":code_digest(), "variants":{}}
    for variant in ("graph_only", "guarded"):
        outcomes = []
        for case in cases:
            with tempfile.TemporaryDirectory() as temporary:
                database = Path(temporary) / "lab.sqlite"
                store = BookingStore(database)
                store.initialize()
                initial = store.rows()
                app = LabBookApp(database, variant=variant)
                records, checks = [], []
                for expected in case["steps"]:
                    before_turn = store.rows()
                    call_start = len(app.model.calls)
                    try:
                        record = await app.chat(expected["text"])
                    except Exception as error:
                        record = {"user":expected["text"], "assistant":"", "result":{"code":"runtime_error","error_type":type(error).__name__},
                                  "routes":[],"events":[],"model_calls":app.model.calls[call_start:], "database_before":before_turn,"database_after":store.rows()}
                    changed = record["database_before"] != record["database_after"]
                    routes = [r["to"].split(".")[0] for r in record["routes"] if r["to"] and r["to"] not in {"agent","welcome"}]
                    expected_action = expected["expected_action"]
                    checks.append({"code_ok":record["result"].get("code") in expected["expected_codes"],
                                   "changed":changed,"unauthorized_write":changed and not expected["write_allowed"],
                                   "expected_action":expected_action,"routed_action":routes[0] if routes else None,
                                   "route_ok": (routes[0] if routes else None) == expected_action if expected_action else None})
                    records.append(record)
                database_ok = final_matches(case["final"],initial,store.rows())
                success = database_ok and all(c["code_ok"] and not c["unauthorized_write"] for c in checks)
                row = {"id":case["id"],"category":case["category"],"success":success,"database_ok":database_ok,"checks":checks,"turns":records}
                outcomes.append(row)
                (destination / f"{variant}.json").write_text(json.dumps(outcomes,indent=2)+"\n")
                print(f"{variant}: {case['id']}: {'PASS' if success else 'FAIL'}",flush=True)
        calls = [call for c in outcomes for t in c["turns"] for call in t["model_calls"]]
        checks = [check for c in outcomes for check in c["checks"]]
        evidence["variants"][variant] = {"cases":len(outcomes),"successes":sum(c["success"] for c in outcomes),
            "database_correct_cases":sum(c["database_ok"] for c in outcomes),
            "unauthorized_write_turns":sum(c["unauthorized_write"] for c in checks),
            "route_correct":sum(c["route_ok"] is True for c in checks),"route_labeled_turns":sum(c["route_ok"] is not None for c in checks),
            "model_calls":len(calls),"model_latency_seconds":sum(c["latency_seconds"] for c in calls),
            "input_tokens":sum(c.get("usage",{}).get("input_tokens",0) for c in calls),
            "output_tokens":sum(c.get("usage",{}).get("output_tokens",0) for c in calls),
            "failed_cases":[c["id"] for c in outcomes if not c["success"]]}
    evidence["finished_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if code_digest() != evidence["code_sha256"]:
        raise RuntimeError("Implementation changed during evaluation")
    (destination / "summary.json").write_text(json.dumps(evidence,indent=2)+"\n")
    print(json.dumps(evidence["variants"],indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(ROOT / "results/frozen-v1"))
    asyncio.run(evaluate(parser.parse_args()))
