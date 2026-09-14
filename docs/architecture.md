# What Arklex does in this project

The inspected upstream version is [ea22ff3e](https://github.com/arklexai/Agent-First-Organization/tree/ea22ff3e0c44b613408e688a3044209a64db35a9). Its roles are easier to understand by separating construction from conversation execution.

## Construction

[`Generator.generate`](https://github.com/arklexai/Agent-First-Organization/blob/ea22ff3e0c44b613408e688a3044209a64db35a9/arklex/orchestrator/generator/core/generator.py) reads configuration and domain documents, asks an LLM to propose tasks and steps, assigns resources, predicts intents, and formats a graph. Our [adapter](../lab_booking/generate.py) records the real prompts, responses, token usage, and generation provenance. It does not replace generation with a handwritten graph.

The generated draft is not executable without review at this snapshot. Its schema differs from the runtime schema, its resource assignments rotate through the resource list, and its proposed steps do not reliably place approval before mutation. The [reviewed compiler](../lab_booking/compile_graph.py) retains the seven generated task names and global intents while replacing the steps and resource bindings with explicit phase templates. [review.json](../generation/review.json) makes this boundary visible. The mapping and phase templates were authored with AI assistance; semantic review is explicit.

Regeneration may change task names. The compiler fails when its reviewed mapping no longer matches the task list. A developer must update the mapping after reviewing the new draft.

## Conversation execution

1. The application calls the public asynchronous `AgentOrg.get_response` API with user text, history, and persisted parameters.
2. `AgentOrg` uses its NLU-agent path for this graph. It is distinct from the optional OpenAI Agents SDK graph path.
3. `NLUAgent.execute` requests the next node from `NLUGraph.get_node`, then sends its resource ID to `Executor.step`. Multiple nodes can run within one turn until a response, incomplete status, or leaf stops execution.
4. The native `IntentDetector` builds its prompts and classifies global or local intents. Our transport records actual model calls without changing those prompts or returning scripted classifications.
5. Small custom Workers extract fields, query tools, display a validated snapshot, commit, discard, or give a bounded fallback response. The field extractor does not choose the business-task route: the graph node supplies the action.
6. Responses announcing successful mutations are rendered from successful database results. No free-form model response can claim a successful booking in this application's registered Worker paths.

Source entry points: [orchestrator](https://github.com/arklexai/Agent-First-Organization/blob/ea22ff3e0c44b613408e688a3044209a64db35a9/arklex/orchestrator/orchestrator.py), [NLU agent](https://github.com/arklexai/Agent-First-Organization/blob/ea22ff3e0c44b613408e688a3044209a64db35a9/arklex/resources/agents/rule_based_agent/nlu_agent.py), [NLU graph](https://github.com/arklexai/Agent-First-Organization/blob/ea22ff3e0c44b613408e688a3044209a64db35a9/arklex/orchestrator/task_graph/nlu_graph.py), [executor](https://github.com/arklexai/Agent-First-Organization/blob/ea22ff3e0c44b613408e688a3044209a64db35a9/arklex/orchestrator/executor/executor.py).

## State and action boundary

The executor instantiates a Worker when it runs a node. A per-conversation `Session`, injected through resource authentication data, therefore owns pending arguments, request revision, displayed fingerprint, current turn, and recent booking ID. Only explicitly provided fields are merged. Internal request IDs are excluded from extraction context.

The guard accepts a confirmation only on a later turn, for the same displayed request fingerprint, with an unconditional affirmative matching the documented grammar. The transaction checks owner, interval, conflict, and idempotency again. Switching to a read task discards an uncommitted write. A rejected ambiguous approval currently requires restating the request, which is a usability limitation worth measuring.

`STAY` would bypass native intent switching in this snapshot, so this application uses ordinary graph nodes and `INCOMPLETE` for missing fields. A documented runtime patch prevents same-intent prediction from advancing past an incomplete node. Both experimental variants use the same patch.

The application does not use the upstream slot filler, retrieval Worker, OpenAI Agents SDK executor, MCTS, reinforcement learning, or live calendar integration. Custom structured field extraction and SQLite are deliberate application components; their results should not be attributed to those unused framework modules.
