"""Offline integrity checks for the public experiment package; no model required."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    manifest=json.loads((ROOT/"evaluation/freeze_manifest.json").read_text())
    assert sha(ROOT/"evaluation/frozen_cases.json")==manifest["sha256"], "Frozen corpus changed"
    summary=json.loads((ROOT/"results/frozen-v1/summary.json").read_text())
    publication=json.loads((ROOT/"generation/publication_edits.json").read_text())["files"]
    assert set(publication) <= set(summary["code_sha256"]), "Untracked publication edit"
    for name,digest in summary["code_sha256"].items():
        if name in publication:
            edit=publication[name]
            assert edit["recorded_sha256"]==digest, f"Recorded source hash changed: {name}"
            assert sha(ROOT/name)==edit["published_sha256"], f"Published source changed: {name}"
        else:
            assert sha(ROOT/name)==digest, f"Evaluated implementation changed: {name}"
    for variant,metrics in summary["variants"].items():
        cases=json.loads((ROOT/f"results/frozen-v1/{variant}.json").read_text())
        assert len(cases)==metrics["cases"]
        assert sum(c["success"] for c in cases)==metrics["successes"]
        assert sum(k["unauthorized_write"] for c in cases for k in c["checks"])==metrics["unauthorized_write_turns"]
        for case in cases:
            assert len(case["checks"])==len(case["turns"])
            for turn,check in zip(case["turns"],case["checks"]):
                assert bool(turn["database_before"]!=turn["database_after"])==check["changed"]
    review=json.loads((ROOT/"generation/review.json").read_text())
    assert sha(ROOT/"generation/taskgraph.raw.json")==review["raw_graph_sha256"]
    assert sha(ROOT/"taskgraph.json")==review["runtime_graph_sha256"]
    simulation=json.loads((ROOT/"results/simulation-v2/summary.json").read_text())
    assert sha(ROOT/"scripts/simulate_users.py")==simulation["harness_sha256"]
    assert sha(ROOT/"evaluation/simulator_goals.json")==simulation["goals_sha256"]
    episodes=json.loads((ROOT/"results/simulation-v2/episodes.json").read_text())
    assert len(episodes)==simulation["episodes"]
    assert sum(e["success"] for e in episodes)==simulation["successes"]
    print("Evidence verified: source and patch hashes, corpus freeze, graph review, paired outcomes, and simulator provenance.")


if __name__=="__main__":
    main()
