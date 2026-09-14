"""Regression for native NLUGraph skipping an INCOMPLETE node after classification."""
import json
import unittest

from lab_booking import ROOT

from arklex.models.llm_config import LLMConfig
from arklex.orchestrator.entities.taskgraph_entities import NLUGraphParams
from arklex.orchestrator.entities.orchestrator_state_entities import StatusEnum
from arklex.orchestrator.task_graph.nlu_graph import NLUGraph

class IncompleteRoutingTests(unittest.TestCase):
    def route(self, selected_action):
        config = json.loads((ROOT / "taskgraph.json").read_text())
        graph = NLUGraph("test", config, llm_config=LLMConfig.model_validate({"llm_provider":"openai","model_type_or_path":"test","langchain_model_kwargs":{"api_key":"local-model","base_url":"http://127.0.0.1:18123/v1"}}))
        intents = {edge[1].split(".")[0]:edge[2]["intent"] for edge in config["edges"] if edge[2]["attribute"]["pred"]}
        graph.intent_detector.execute = lambda *_: intents[selected_action]
        parameters = NLUGraphParams(curr_node="book.collect",curr_global_intent=intents["book"],node_status={"book.collect":StatusEnum.INCOMPLETE})
        node, _ = graph.get_node({"text":"2026-10-08, 13:30 to 14:30.","chat_history_str":"User supplies the requested missing fields.","nlu_params":parameters,"allow_global_intent_switch":True})
        return node.node_id

    def test_same_intent_reexecutes_incomplete_collection(self):
        self.assertEqual("book.collect",self.route("book"))

    def test_new_intent_can_interrupt_incomplete_collection(self):
        self.assertEqual("policy.query",self.route("policy"))


if __name__ == "__main__":
    unittest.main()
