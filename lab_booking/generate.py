"""Run the actual pinned Arklex Generator and preserve its unreviewed output."""

import argparse
import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from langchain_openai import ChatOpenAI

from . import ROOT
from .model import ModelClient

logging.getLogger("arklex.resources.resource_map").setLevel(logging.CRITICAL)


class RecordedModel:
    def __init__(self, client, destination):
        self.model = ChatOpenAI(model=client.model_name, base_url=client.base_url,
                               api_key=client.api_key, temperature=0, seed=42,
                               max_tokens=2300, timeout=120, max_retries=0)
        self.destination = destination
        self.records = []

    def _call(self, method, value, **kwargs):
        started = time.perf_counter()
        response = getattr(self.model, method)(value, **kwargs)
        text = response.content if hasattr(response, "content") else response.generations[0][0].text
        usage = getattr(response, "usage_metadata", None) or getattr(response, "llm_output", {})
        self.records.append({"method": method, "input": str(value), "output": text,
                             "seconds": time.perf_counter() - started, "usage": usage})
        self.destination.write_text(json.dumps(self.records, indent=2, ensure_ascii=False) + "\n")
        print(f"Generator model call {len(self.records)}: {method}, {len(text)} characters", flush=True)
        return response

    def invoke(self, value, **kwargs):
        return self._call("invoke", value, **kwargs)

    def generate(self, value, **kwargs):
        return self._call("generate", value, **kwargs)


def run(output):
    if not (ROOT / ".vendor/manifest.json").exists():
        raise RuntimeError("First run python scripts/prepare_upstream.py")
    from arklex.orchestrator.generator.core.generator import Generator

    output.mkdir(parents=True, exist_ok=True)
    config = json.loads((ROOT / "config.json").read_text())
    provenance = {}
    for kind in ("task_docs", "instruction_docs"):
        for item in config[kind]:
            relative = item["source"]
            path = ROOT / relative
            provenance[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
            item["source"] = str(path)
    client = ModelClient(config["llm"])
    model = RecordedModel(client, output / "model_calls.json")
    generator = Generator(config=config, model=model, output_dir=str(output), interactable_with_user=False)
    graph = generator.generate()
    if not graph.get("tasks") or not graph.get("edges"):
        raise RuntimeError("Generator produced no usable tasks/edges; inspect model_calls.json")
    # Remove local absolute paths from the shareable artifact, without changing tasks or topology.
    serialized = json.dumps(graph, indent=2, ensure_ascii=False).replace(str(ROOT) + "/", "")
    (output / "taskgraph.raw.json").write_text(serialized + "\n")
    (output / "tasks.raw.json").write_text(json.dumps(graph["tasks"], indent=2) + "\n")
    (output / "provenance.json").write_text(json.dumps({
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "upstream_commit": "ea22ff3e0c44b613408e688a3044209a64db35a9",
        "entrypoint": "arklex.orchestrator.generator.core.generator.Generator.generate",
        "compatibility_patch": "patches/generator-compatibility.patch",
        "source_documents_sha256": provenance,
        "model": client.model_name, "temperature": 0, "seed": 42,
        "model_calls": len(model.records), "tasks": len(graph["tasks"]),
        "nodes": len(graph["nodes"]), "edges": len(graph["edges"]),
        "review_status": "unreviewed; raw output is not used for database actions",
    }, indent=2) + "\n")
    print(f"Generated {len(graph['tasks'])} tasks and {len(graph['nodes'])} nodes.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "generation")
    args = parser.parse_args()
    run(args.output)
