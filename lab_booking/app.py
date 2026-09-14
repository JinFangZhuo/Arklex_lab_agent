"""Real asynchronous AgentOrg API, with auditable native NLU and tool traces."""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import logging
from pathlib import Path

logging.getLogger("arklex.resources.resource_map").setLevel(logging.CRITICAL)

from arklex.models.llm_config import LLMConfig
from arklex.orchestrator.executor.executor import Executor
from arklex.orchestrator.orchestrator import AgentOrg
from arklex.resources.resource_map import RESOURCE_MAP

from . import ROOT
from .database import BookingStore
from .model import ModelClient
from .worker import Session, WORKERS


class RecordedTransport:
    """Only replace model transport for logging; preserve native prompts/classification."""
    def __init__(self, model):
        self.model = model

    def get_response(self, prompt):
        return self.model.call([("human", prompt)], purpose="arklex_intent", max_tokens=256)

    def get_response_with_structured_output(self, prompt, schema):
        schema = copy.deepcopy(schema)
        schema["additionalProperties"] = False
        return json.loads(self.model.call([("human", prompt)], purpose="arklex_intent", schema=schema, max_tokens=256))


class LabBookApp:
    def __init__(self, database, *, variant="guarded", user_id="alice", config=None):
        if variant not in {"guarded", "graph_only"}:
            raise ValueError(variant)
        self.config = config or json.loads((ROOT / "config.json").read_text())
        self.model = ModelClient(self.config["llm"])
        self.session = Session(BookingStore(database), self.model, user_id, variant)
        graph = json.loads((ROOT / "taskgraph.json").read_text())
        graph["llm_config"] = graph["guardrail_llm_config"] = self.model.llm_config()
        for resource_id, cls in WORKERS.items():
            RESOURCE_MAP[resource_id] = {"item_cls": cls}
        executor = Executor(tools=[], workers=graph["workers"], nodes=graph["nodes"], llm_config=LLMConfig.model_validate(graph["llm_config"]))
        for resource_id in WORKERS:
            executor.workers[resource_id]["auth"]["session"] = self.session
        self.orchestrator = AgentOrg(config=graph, executor=executor)
        self.orchestrator.nlu_graph.intent_detector.model_service = RecordedTransport(self.model)
        self.routes = []
        native_get_node = self.orchestrator.nlu_graph.get_node

        def recorded_get_node(inputs):
            before = inputs["nlu_params"].curr_node
            node, parameters = native_get_node(inputs)
            self.routes.append({"from": before, "to": node.node_id, "resource": node.resource,
                                "nlu_records": copy.deepcopy(parameters.nlu_records)})
            return node, parameters

        self.orchestrator.nlu_graph.get_node = recorded_get_node
        self.history, self.parameters, self.turns = [], {}, []

    async def chat(self, message):
        if not self.history and message != "<start>":
            await self.chat("<start>")
        self.session.turn += 1
        self.session.last_result = {}
        c, e, r = len(self.model.calls), len(self.session.events), len(self.routes)
        before = self.session.store.rows()
        output = await self.orchestrator.get_response({"text": message, "chat_history": self.history, "parameters": self.parameters})
        self.parameters = output["parameters"]
        self.history.extend([{"role": "user", "content": message}, {"role": "assistant", "content": output["answer"]}])
        record = {"user": message, "assistant": output["answer"], "result": copy.deepcopy(self.session.last_result),
                  "events": copy.deepcopy(self.session.events[e:]), "model_calls": self.model.calls[c:],
                  "routes": self.routes[r:], "database_before": before, "database_after": self.session.store.rows()}
        self.turns.append(record)
        return record


async def interactive(args):
    store = BookingStore(args.database)
    if not store.path.exists():
        store.initialize()
    app = LabBookApp(args.database, user_id=args.user)
    print((await app.chat("<start>"))["assistant"])
    while True:
        try:
            message = input("You (/quit to exit): ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if message == "/quit":
            break
        if message:
            print("LabBook:", (await app.chat(message))["assistant"])
    if args.transcript:
        Path(args.transcript).write_text(json.dumps(app.turns, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default=str(ROOT / "runtime/lab.sqlite"))
    parser.add_argument("--user", default="alice")
    parser.add_argument("--transcript")
    asyncio.run(interactive(parser.parse_args()))
