# Scope, limitations, and attribution

This is an application study and engineering prototype, not a new state-of-the-art agent algorithm.

- **Synthetic environment.** Instruments, users, reservations, and user goals are fixtures. SQLite mutations are real, but no external laboratory, hardware, calendar, or payment system is affected. `--user` is a demonstration identity supplied by the application, not a production authentication mechanism.
- **Small, authored evaluation.** The fixed cases were designed for this application and frozen before their first run. They are not an independently collected blind benchmark. Development conversations and tests were used to fix the implementation before evaluation. Frozen failures must remain visible.
- **One agent model and decoding setup.** Quantized Qwen2.5-3B-Instruct with deterministic generation does not represent larger proprietary models or other deployments. Seeds do not guarantee identical output across hardware and runtime versions. The model and runtime hashes are recorded.
- **Ablation scope.** `graph_only` is an experimental variant of this application, not unmodified Arklex or a competing agent framework. Both variants share the incomplete-node patch, graph, extraction prompts, snapshot checks, and transaction code. Only the final affirmative grammar differs.
- **Simulator dependence.** The adaptive simulator and agent use the same model family. Eight episodes cannot establish realistic population coverage, unbiased success rates, or equivalence to SAGE. Simulated success is scored from database state, not the simulator's claim that it is done.
- **Confirmation usability.** A bounded grammar rejects some valid natural approvals. A rejected approval currently asks the user to restate the request. An unambiguous button or signed request token would avoid this language-recognition tradeoff but requires a different interface.
- **Generated plans need review.** The raw generator output is retained. Executable phases and resource bindings are explicitly authored, with a task-name check and a review record. Automatic safe compilation has not been solved here.
- **Live runtime behavior.** A session is intended for sequential messages. Multi-client session storage, adversarial load testing, authentication, distributed locking, and operational monitoring are outside this prototype.
- **No statistical superiority claim.** Results describe observed cases and traces. No framework-wide improvement or general safety guarantee follows from them. Latency is measured locally and includes transport/model service time rather than a standardized benchmark environment.

## Attribution and AI assistance

Arklex is the upstream framework; its authors retain credit for generation, NLU orchestration, and resource execution. Qwen and llama.cpp provide the model and inference runtime. Patches include small excerpts of upstream code and should be read with the upstream MIT license declaration and attribution.

The application, source analysis, experimental design, tests, and documentation were developed with substantial AI coding-assistant help. Recorded model calls, database outcomes, and regression tests provide the execution evidence.

Related papers are cited as motivation or comparison, not as algorithms reproduced in this repository.
