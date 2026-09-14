"""Fetch a pinned Arklex snapshot and apply reviewed compatibility/runtime fixes.

The original checkout is never modified. Exact old text is checked before edits.
The generated diff is the reviewable patch distributed with this project.
"""

import argparse
import difflib
import hashlib
import json
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "ea22ff3e0c44b613408e688a3044209a64db35a9"
FIXES = {
    "arklex/orchestrator/generator/core/generator.py": (
        "from arklex.orchestrator.executor.executor import (\n    BaseResourceInitializer,\n    DefaultResourceInitializer,\n)",
        "from arklex.resources.resource_loader import ResourceLoader as BaseResourceInitializer\nfrom arklex.resources.resource_loader import ResourceLoader as DefaultResourceInitializer",
    ),
    "arklex/orchestrator/generator/docs/document_loader.py": (
        '        if str(doc_path) in self._cache:\n            document = self._cache[str(doc_path)]',
        '        doc_path = Path(doc_path)\n        if str(doc_path) in self._cache:\n            document = self._cache[str(doc_path)]',
    ),
    "arklex/orchestrator/task_graph/nlu_graph.py": (
        '            if pred_intent and pred_intent != self.unsure_intent.get("intent"):',
        '            if (\n                pred_intent\n                and pred_intent != self.unsure_intent.get("intent")\n                and params.node_status.get(curr_node, StatusEnum.COMPLETE) != StatusEnum.INCOMPLETE\n            ):',
    ),
}


def prepare(source=None):
    target = ROOT / ".vendor/arklex"
    if target.exists():
        manifest = json.loads((ROOT / ".vendor/manifest.json").read_text())
        for filename, digest in manifest["patched_sha256"].items():
            if hashlib.sha256((target / filename).read_bytes()).hexdigest() != digest:
                raise RuntimeError(f"Patched upstream file changed: {filename}")
    else:
        with tempfile.TemporaryDirectory() as temporary:
            if source is None:
                archive = Path(temporary) / "source.tar.gz"
                url = f"https://codeload.github.com/arklexai/Agent-First-Organization/tar.gz/{COMMIT}"
                with urllib.request.urlopen(url, timeout=90) as response, archive.open("wb") as output:
                    shutil.copyfileobj(response, output)
                with tarfile.open(archive) as handle:
                    handle.extractall(temporary, filter="data")
                source = Path(temporary) / f"Agent-First-Organization-{COMMIT}"
            shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", ".git"))
    patches = {"generator-compatibility.patch": [], "runtime-incomplete.patch": []}
    hashes = {}
    for filename, (old, new) in FIXES.items():
        path = target / filename
        original = path.read_text()
        if new in original:
            original = original.replace(new, old)
        if original.count(old) != 1:
            raise RuntimeError(f"Unexpected pinned source at {filename}")
        changed = original.replace(old, new)
        path.write_text(changed)
        hashes[filename] = hashlib.sha256(path.read_bytes()).hexdigest()
        name = "runtime-incomplete.patch" if "task_graph/nlu_graph" in filename else "generator-compatibility.patch"
        patches[name].extend(difflib.unified_diff(original.splitlines(True), changed.splitlines(True),
                                        fromfile=f"a/{filename}", tofile=f"b/{filename}"))
    for name, lines in patches.items():
        (ROOT / "patches" / name).write_text("".join(lines))
    (ROOT / ".vendor/manifest.json").write_text(json.dumps({"commit": COMMIT, "patched_sha256": hashes}, indent=2) + "\n")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, help="Optional existing clean pinned source directory")
    args = parser.parse_args()
    print(prepare(args.source))
