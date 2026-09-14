# Reproducible findings in the pinned Arklex source

These observations concern commit `ea22ff3e0c44b613408e688a3044209a64db35a9`, not every Arklex release. The included patches and regression tests document the observed behavior at that snapshot.

## 1. Same-intent prediction can skip an incomplete node

**Trigger:** a collection node has status `INCOMPLETE`, a sequential `none` edge leads to confirmation, and the user's next message is classified as the current global intent.

**Observed behavior:** `NLUGraph.get_node` calls `handle_random_next_node` after that prediction, before checking `handle_incomplete_node`. The collection Worker does not receive the newly supplied fields. In the initial development conversation, `Book P1` followed by a date/time displayed an incomplete request, then failed on confirmation.

**Expected behavior:** remain on the incomplete node for the same task, while permitting a different global task to interrupt it.

The [minimal patch](../patches/runtime-incomplete.patch) guards only that early sequential advance. Two [native graph regression tests](../tests/test_nlu_incomplete.py) mock classification to isolate routing: same intent must re-execute collection; a different intent must switch tasks. Before the patch, the first test failed with `book.collect != book.confirm`, while the second passed. After the patch, both pass. The [real-model repaired dialogue](../results/development_repair.json) also completes collection and commits after confirmation.

The confirmation Worker additionally validates completeness before displaying a request. This application-level check prevents a future unexpected graph transition from treating an incomplete proposal as ready to execute.

## 2. Generator import and document-path compatibility

The generator imports `BaseResourceInitializer` and `DefaultResourceInitializer` from `executor.py`, where those symbols do not exist in this snapshot. The available `ResourceLoader` supplies the needed initialization interface. Also, the instruction-document loader receives a JSON string path but calls methods expecting `Path`.

The [compatibility patch](../patches/generator-compatibility.patch) aliases the real resource loader and converts that path to `Path`. With these changes, the official generation entry point completes 18 real model calls and writes its draft. The changes do not alter task-generation prompts or substitute canned model outputs.

## 3. Resource binding is round-robin

[`BestPracticeManager.finetune_best_practice`](https://github.com/arklexai/Agent-First-Organization/blob/ea22ff3e0c44b613408e688a3044209a64db35a9/arklex/orchestrator/generator/tasks/best_practice_manager.py#L220) indexes the list of available resources with `resource_index % len(available_resources)`. This is not semantic tool selection.

The raw equipment-listing task consequently associates different conversational steps with collection, confirmation, commit, and query Workers. The generated reservation flow also places a creation step before a later proceed question. These observations are preserved in [tasks.raw.json](../generation/tasks.raw.json). The runtime uses explicitly reviewed bindings rather than executing those assignments.

**Suggested improvement:** validate that read tasks cannot invoke mutation resources, require typed inputs/outputs for each step, and flag writes without an approval predecessor. Such a linter would catch structural mistakes before a user conversation. Semantic correctness would still require runtime checks and evaluation.

## 4. Generator and runtime graph schemas have drifted

The generator emits `type: start` and `attribute.value`; the inspected runtime expects an agent root with `attribute.start`, node `data`, and compatible resource IDs. The [review compiler](../lab_booking/compile_graph.py) converts the draft into this application's executable graph and records a checksum and task mapping.

**Suggested improvement:** add an integration test that generates a small draft, loads it into `AgentOrg`, and executes one read and one confirmed write against fixture tools. Unit tests of generation and orchestration alone can miss this boundary.

## Patch coverage

The incomplete-node patch covers same-intent continuation and preserves interruption by a different task. Deterministic tests and a recorded dialogue verify that behavior. Resource-binding validation and generator/runtime schema checks remain open engineering work.
