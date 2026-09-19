# Measuring the Value of Generated Tools, Skills, and Guidance

Research and implementation plan for CyberAgentFlow and ScenarioForge

Date: 2026-09-17  
Status: Proposed study and software roadmap; experiments have not been conducted.

## 1. Purpose

Evaluate whether adding a generated tool, skill, playbook, markdown guide, or other knowledge artifact improves an agent's ability to complete cybersecurity tasks. Measure verified outcomes, reliability, resource use, and operator effort rather than response appearance or tool-call counts alone.

CyberAgentFlow supplies the agent, artifact generation workflow, and execution records. ScenarioForge supplies versioned scenarios, deployment into CORE, readiness checks, and information from which evaluator-only ground truth can be constructed. An experiment coordinator connects the two.

The central question is:

> Under comparable starting conditions and budgets, does making a frozen artifact available improve verified task success, and at what cost?

Exact replay is useful for debugging and demonstrations. It is not sufficient evidence of improvement. The main experiment measures outcome distributions across tasks, repetitions, and, when available, several fixed scenarios.

## 2. Scope and claims

Distinguish three levels of evidence:

1. **Artifact efficacy:** a particular frozen artifact improves performance on a specified task suite.
2. **Generation efficacy:** the artifact-generation process reliably produces useful artifacts across multiple development problems and generation attempts.
3. **Transfer:** artifacts remain useful on held-out tasks and scenarios beyond the examples used to produce them.

A successful demonstration of one selected artifact supports the first claim. It does not establish the second or third. A single CORE scenario supports a case study within that environment, even if the experiment includes many repeated runs.

Initial scope should be observational tasks that can be repeated without intentionally changing the target environment. State-changing tasks require a validated restoration procedure or must be reported as a separate exploratory study with carryover limitations.

## 3. Research questions and hypotheses

Predeclare the primary research question and analysis before evaluating the held-out suite.

| ID | Research question | Proposed measurement |
| --- | --- | --- |
| RQ1 | Does artifact availability improve task completion? | Difference in verified success within a fixed budget |
| RQ2 | Does it reduce the resources needed to achieve useful results? | Success–cost tradeoff, token use, elapsed time, and underlying tool work |
| RQ3 | Does it improve consistency? | Per-task success probabilities, repeated-trial reliability, and failure variation |
| RQ4 | Where does the benefit come from? | Guidance-only, tool-only, and combined ablations |
| RQ5 | Does the benefit transfer? | Effects on held-out tasks, scenario variants, and scenario families |
| RQ6 | Does the generation process produce useful artifacts reliably? | Improvement across generated candidates, including failed generation and repair costs |
| RQ7 | Can an added artifact make performance worse? | Per-task regressions, unnecessary use, unsupported findings, and policy violations |

The primary hypothesis can be that the combined condition increases verified success relative to baseline. Secondary hypotheses concern cost and reliability. Report null and negative findings rather than assuming every artifact helps.

If the intended claim is equal success at lower cost, predefine an acceptable success-rate loss and use an appropriate noninferiority design. A nonsignificant success difference does not establish equivalence.

## 4. Experimental objects and identifiers

Use explicit records rather than inferring experimental membership from run names.

| Object | Contents |
| --- | --- |
| Scenario snapshot | Scenario ID, family, resolved plan, artifact manifest, dependency/image identifiers, and hashes |
| Task | Prompt, starting context, target scope, task family, split, budgets, and verifier reference |
| Artifact snapshot | Exact content/code, dependency manifest, version hash, generation lineage, and activation mode |
| Condition | Baseline settings plus an explicit set of tools, guidance, and activation rules |
| Experiment | Frozen suite, conditions, repetition schedule, ordering seed, hypotheses, and analysis plan |
| Trial | One execution of a task under a condition, model configuration, scenario instance, and repetition |
| Attempt | An original execution or a linked retry; retries never overwrite the original record |
| Evaluation | Versioned verifier output, evidence references, checks, score, and failure classification |

Associate each trial with the parent experiment, task, scenario snapshot, scenario session, condition, artifact hashes, and CyberAgentFlow run ID.

## 5. Task and scenario suite

### Task design

Define tasks with independently checkable requirements. Candidate task families include:

- Discover exposed hosts and services within an allowed target scope.
- Identify service versions and attach supporting observations.
- Determine whether specified communication paths are reachable.
- Explain a segmentation or reachability failure using collected evidence.
- Produce a structured inventory from several observations.
- Interpret a supplied evidence bundle without collecting new live data.

Example task:

> Identify exposed HTTP services in the allowed subnet. Report each host and port, attach supporting evidence, and do not probe excluded targets.

Success criteria should specify required coverage, tolerated error levels, evidence requirements, and any policy constraints. Correct answers should not depend on following a particular command sequence.

Include easy, moderate, and difficult tasks. Include tasks where the artifact is relevant and tasks where it should be unnecessary. The latter reveal distraction, inappropriate invocation, and added context costs.

Do not count superficial paraphrases as independent task coverage. Tag related variants with a shared task-family identifier.

### Development and held-out splits

Create separate development, validation, and final test partitions:

- **Development:** source interactions used to generate and repair artifacts.
- **Validation:** used to choose artifact versions and experiment settings.
- **Test:** held out from generation, repair, selection, and prompt tuning.

Freeze artifacts and evaluation rules before running the final test partition. A held-out prompt is not sufficient if its answer or near-identical solution appeared in the generation transcript.

Evaluate exact-task reuse separately when it is a product goal. Label it as reuse on previously observed tasks, rather than transfer.

### ScenarioForge's role

The current ScenarioForge repository provides useful building blocks:

- Scenario XML, optional generation seeds, and persisted topology plans.
- CORE deployment and session lifecycle operations.
- Runtime artifact checks for services, reachability, segmentation, containers, and related setup.
- Reproduction bundles with manifests and hashes.
- Participant and facilitator guides with audience-specific content.

These capabilities support environment preparation. They are not yet an integrated agent benchmark or proof of complete environment reset. Task-specific verifiers must still be implemented.

Use three scenario partitions where practical:

| Partition | Purpose |
| --- | --- |
| Development scenarios | Generate and refine artifacts |
| Held-out variants | Test different addressing, placement, size, or topology details within familiar families |
| Held-out families | Test transfer to structurally different environments and task combinations |

Keep each scenario fixed while comparing conditions within it. Then repeat the comparison across several fixed scenarios. This preserves controlled comparisons while broadening the evaluation beyond one CORE deployment.

Freeze resolved scenarios before final evaluation. Archive plans, generated assets, image digests where available, generator versions, and hashes. A scenario-generation seed alone does not preserve changing catalogs, images, or external dependencies.

Facilitator answers, flags, full topology secrets, and verifier expectations belong to the evaluator. They must not enter the agent's prompt, accessible files, or artifact-generation context unless explicitly part of the task.

## 6. Conditions and ablations

For an executable tool with accompanying guidance, use a four-condition design:

| Condition | Agent receives | Main comparison |
| --- | --- | --- |
| A: Baseline | Existing tools and standard instructions | Reference performance |
| B: Guidance only | Baseline plus generated procedural guidance | B−A: knowledge contribution |
| C: Tool only | Baseline plus generated tool and its necessary interface description | C−A: executable contribution |
| D: Combined | Baseline plus generated tool and guidance | D−A: total contribution; D−C: additional guidance contribution |

The interaction contrast, D−C−B+A, can help assess whether code and guidance reinforce one another. Treat it as a prespecified secondary analysis unless it is the primary research question.

Tool-only still needs an accurate callable schema and minimum interface description. It should omit the additional procedural playbook, not essential invocation information.

For a standalone document, compare baseline with baseline plus the document. For a claim about skill packaging, compare the packaged skill with the same substantive instructions supplied as ordinary markdown. Without this control, gains could come from information rather than the packaging or activation mechanism.

Additional diagnostic conditions may include expert-authored guidance or forced artifact invocation. Natural artifact availability remains the primary condition: recognizing when to load or use an artifact is part of its practical benefit.

Keep baseline access to underlying primitives comparable. If the new tool adds privileged access or genuinely new capabilities, state that explicitly rather than attributing the full gain to orchestration efficiency.

Record exactly what the agent received. Guides may be truncated; skills may never be loaded; retrieved documents may only contribute selected chunks. Availability, loading, retrieval, and invocation are distinct events.

## 7. Repetition, seeds, and replay modes

### Seeded live experiments

Use the same predefined set of distinct seeds across conditions when the model backend supports them. Freeze the other generation settings. Matching seeds is a control, not a guarantee of identical trajectories or perfectly coupled randomness.

Repeated deterministic executions of the identical request with the same seed are repeatability checks; they should not be presented as independent samples of model sampling variability.

There are several independent seed concepts:

- Scenario-generation seed.
- Model-generation seed or per-call seed schedule.
- Experiment-order randomization seed.
- Seeds used by tools or scenario services, where exposed.

Record them separately. Apply the model settings to all relevant calls, including summaries, fallback calls, and retries. Record unsupported or rejected parameters rather than silently claiming they were applied.

A fixed seed does not control network timing, runtime state, tool output order, timestamps, backend numerical behavior, or the input changes caused by a different tool set. Ollama documents seeded generation; OpenAI describes its Chat Completions seed behavior as best effort rather than guaranteed determinism [5, 6]. Backend support must be verified for the actual study configuration.

### Repeat and replay modes

| Mode | Behavior | Research use |
| --- | --- | --- |
| Recording playback | Display saved prompts, responses, and outputs without executing them | Exact demonstration and trace inspection |
| Seeded live repeat | Fresh model decisions and real tool execution from the same starting context | Main live evaluation and consistency measurement |
| Repeat with changed artifacts | Fresh trial with a different tool/guidance condition | Controlled artifact comparison |
| Recorded command replay | Execute saved calls and arguments in sequence without fresh model planning | Isolate changes in execution and environment behavior |
| Regenerate from saved evidence | Give the model a frozen evidence bundle and generate a new response | Isolate analysis quality from evidence collection |
| Recorded tool-result substitution | Return recorded outputs for matching tool calls | Diagnostic model-loop evaluation under controlled observations |

Recorded command replay fixes the requested sequence, not necessarily runtime handles, timing, results, or final state. Interactive session identifiers may require explicit mapping.

Recorded tool-result substitution must match the recorded call context, arguments, and sequence. An unmatched call should stop or mark the trial unsupported; it must not silently execute live or invent an output. This mode cannot fully evaluate a new tool whose behavior is absent from the recording.

Support fresh conversation and a checkpoint immediately before a chosen prompt. Do not repeat at the end of the old chat and call it an equivalent trial: that exposes the previous answer.

Add a first-divergence report comparing the first changed model request, response, tool call, or tool result. Preserve raw data even if a diagnostic view normalizes timestamps or output ordering. Normalization must not erase meaningful differences.

## 8. Execution protocol and environment control

For each task/scenario/repetition block:

1. Select the frozen scenario snapshot and verify its identity.
2. Deploy it or attach to a qualifying running instance.
3. Run predefined readiness and relevant state checks.
4. Randomize condition order using the stored schedule.
5. Establish the condition's starting environment and create a fresh agent session.
6. Load frozen tools and guidance from the condition snapshot.
7. Execute the task under the specified budgets and interaction policy.
8. Capture outputs, internal work, interventions, and post-trial observations.
9. Run the independent verifier.
10. Commit records, clean up trial-owned processes, and proceed only when lifecycle checks pass.

Run sequentially on a shared CORE target. Hold a target lease/lock that prevents another experiment or interactive session from interfering with the trial.

Randomization reduces systematic ordering effects, but does not eliminate persistent carryover. If trials change target state, use a tested restoration procedure that covers relevant containers, volumes, files, services, and sessions. Stopping and starting CORE alone is not evidence that all such state has been restored.

If the study keeps the live CORE VM untouched between trials, restrict the primary suite to observational tasks and document residual state uncertainty. Read-only operations can still affect caches, load, logs, and connection state. Readiness checks detect specified forms of drift, not complete state equivalence.

Predefine infrastructure-failure and drift handling. Preserve all original attempts and report their frequency by condition. Retry only according to a uniform policy; do not rerun only disappointing results. Agent-caused timeouts and failures remain task outcomes.

## 9. Budgets and human involvement

Use comparable wall-clock and model-token budgets, with any additional compute or network limits documented. A fixed count of top-level tool calls is not a fair primary budget when one condition can package many operations into a wrapper.

Record actual usage, not just limits. Define whether setup, model loading, cached requests, and cleanup are included in elapsed time; report setup separately where relevant.

Choose and freeze the interaction policy:

- Allowed tool actions and target exclusions.
- Treatment of timeout checkpoints.
- Whether operator assistance is permitted.
- What constitutes an intervention or assisted completion.
- Handling of approval waits and whether they count toward elapsed time.

An unattended experiment should use an explicitly authorized action set and bounded timeout behavior. It should not silently inherit an operator's ad hoc clicks or remove safeguards solely to keep trials running.

For an assisted study, standardize operator instructions and record active assistance time separately from ordinary runtime waiting. A button-click count alone is not a complete measure of human effort.

Keep logging settings constant across conditions. CyberAgentFlow's current default policy is to enable logging except network capture; enable capture for a study only if required and apply it consistently.

## 10. Ground truth and verification

Use executable assertions where possible. A discovery verifier might check:

- Reported host/port/service tuples against evaluator-maintained truth.
- Required coverage of reachable services.
- Whether cited evidence supports the reported claims.
- Whether actions remained within the allowed scope.

Separate scenario readiness from task success. A scenario can be healthy while the agent fails its task; conversely, an agent should not be blamed for a missing service caused by failed deployment.

Store structured final findings alongside the human-readable response. Keep the output contract identical across conditions. If parsing requires a model, log that evaluator call and validate its behavior; deterministic grading should not hide an unmeasured model-based extraction step.

For qualitative reporting tasks, use a fixed rubric and blinded human reviewers. Specify adjudication and inter-rater agreement procedures. An LLM judge may supplement evaluation but should not be the sole basis for factual correctness or the agent's own self-assessment.

Version verifiers and retain per-check evidence. Validate them with known-good solutions, known-bad outputs, and edge cases before freezing the final suite. Do not tune the verifier to favor a tested artifact.

## 11. Metrics

### Primary endpoint

Use **verified task success within the predefined budget**. Specify before evaluation whether success requires every mandatory check and no policy violation. Always report raw completion and policy outcomes separately as well.

### Secondary measurements

| Dimension | Measurements and interpretation |
| --- | --- |
| Finding quality | Precision, recall, unsupported claims, missed required findings, and evidence validity |
| Model resources | Input/output tokens, reported cached/reasoning usage where available, model calls, retries, and summaries |
| Execution resources | Wall-clock time, underlying commands, nested tool calls, internal model calls, and available CPU/network measurements |
| Human effort | Interventions, corrections, approvals, and active assistance time |
| Reliability | Per-task success rates and probability of repeated success |
| Artifact adoption | Availability, loading, retrieval, invocation, failures, and unnecessary use |
| Compliance | Attempted and completed out-of-scope actions and other predefined rule violations |
| Generation process | Candidate success/failure, repair attempts, selection effort, and creation costs |

Do not equate the context-window token estimate with provider-reported usage. Missing usage is unknown, not zero. Do not call token counts monetary cost unless a documented pricing calculation supports that conversion.

Use success–cost plots and completion-versus-budget curves. Report costs across all attempts. Successful-runs-only timing is a secondary, explicitly conditional metric, because difficult failed runs can otherwise disappear from the cost comparison.

For repeated-trial reliability, consider pass^k: success across all k repetitions. Distinguish it from pass@k, which asks whether at least one of k attempts succeeds [3]. Choose k before reporting and use enough repetitions to estimate it meaningfully.

Count internal work. One generated tool that runs ten subprocesses or invokes another model should not appear to consume only one inexpensive operation.

### Generation cost and amortization

Report artifact creation, testing, repair, and selection costs separately from reuse costs. Include unsuccessful candidates if evaluating the generation method.

When task quality is comparable and the augmented condition has positive per-use savings, a descriptive break-even estimate is:

`break-even uses = total creation cost / mean per-use savings`

Use consistent units and report uncertainty. If the artifact changes success rates materially, show the quality–cost tradeoff rather than treating the ratio as a complete economic conclusion.

## 12. Sample size and statistical analysis

A planning example is 30 held-out tasks × 10 distinct seeds × 4 conditions = 1,200 trials per model. This is a pilot-sized design example, not a guarantee of adequate statistical power. Start smaller to debug the pipeline, then use observed variance, clustering, expected effect size, and available resources to plan the confirmatory study.

Prefer additional genuinely different tasks and scenarios over many identical repetitions. Allocate tasks across scenario and task families deliberately rather than allowing one large family to dominate the average.

Analysis should:

- Report paired differences in success rate in percentage points, with 95% confidence intervals.
- Preserve the pairing of conditions when resampling or fitting models.
- Account for trials nested within tasks, related task variants, and scenarios.
- Treat seeds as repetitions, not independent scenario samples.
- State whether aggregation weights scenarios, tasks, or trials equally.
- Include artifact-generation lineage when making claims about generation efficacy.

For a single scenario, task-group bootstrap intervals can describe uncertainty over the evaluated task population. They cannot support claims about variation across scenarios. With sufficient independent scenarios, use a hierarchical or cluster-based analysis that resamples scenarios and relevant nested task groups while preserving condition pairs. With very few scenarios, report per-scenario results and limited generalization rather than overstating interval precision.

A mixed-effects analysis may be appropriate, but choose its structure based on the final design. Do not treat every tool call or model turn as an independent experimental observation.

Predeclare one primary contrast and endpoint. Label other analyses exploratory or apply a stated multiple-comparison procedure. Report practical effect sizes alongside significance, including negative effects and artifact-specific regressions.

## 13. Software additions to CyberAgentFlow

### Existing foundations

The repository already includes `MCPSession`, session/message persistence, tool-call records, a SQLite event store, generated-artifact fingerprints, tool tests, and document validation. These support the implementation but do not constitute an experiment runner or efficacy evaluator.

### Required components

| Component | Required behavior |
| --- | --- |
| Experiment store | Persist suites, conditions, schedules, trial attempts, evaluations, and lineage with explicit IDs |
| Immutable snapshot store | Preserve artifact contents, tools, effective instructions, settings, and dependency identifiers |
| Reusable execution service | Run `MCPSession` for either live chat or an isolated experiment trial |
| Trial scheduler | Sequential execution, target locking, budgets, cancellation, restart recovery, and auditable retries |
| Checkpoint capture | Save starting context before each prompt and effective requests throughout execution |
| Provider telemetry | Preserve reported usage, latency, model identity, and requested/effective generation settings |
| Artifact activation layer | Distinguish tool execution, text injection, optional document reads, skill loading, and retrieval |
| Nested-operation telemetry | Link subprocesses, internal tool calls, and internal model calls to their parent artifact invocation |
| Verifier runner | Keep evaluator-only data outside the agent environment and store versioned check results |
| Environment adapter | ScenarioForge deployment, readiness, lifecycle, and scenario identity integration |
| Analysis/export layer | Paired results, uncertainty estimates, trace links, and machine-readable exports |

The current web session state and tool configuration are shared. Refactor them so each trial has isolated configuration and output paths. Avoid implementing evaluation by repeatedly clicking the existing chat UI.

Current message persistence is updated during conversation; add immutable pre-prompt checkpoints. Provider adapters should retain usage metadata rather than reducing every response to only message content and tool calls.

Research runs must explicitly control tool and document selection. The normal Tools-page convenience of automatically selecting a tool's guide must not contaminate a tool-only condition.

Tool guides and playbooks already have runtime loading paths. Other generated document types require defined activation semantics before they can be evaluated as active skills or knowledge sources. Document validation alone does not establish consumption by the agent.

Audit event-store persistence: a trial should not be marked complete until required records are committed, and write failures must be surfaced. Flag incomplete telemetry in exports rather than silently calculating complete-looking metrics from missing records.

Illustrative new modules could be `experiments/store.py`, `snapshots.py`, `runner.py`, `scenarioforge_adapter.py`, `verifiers/`, and `analysis.py`. Names are proposals, not existing APIs.

## 14. ScenarioForge integration contract

Build an adapter over supported CLI/API operations rather than assuming every existing UI route is already a stable automation interface.

The adapter should expose operations conceptually equivalent to:

1. Resolve a frozen scenario snapshot and its manifest.
2. Deploy or attach to the intended CORE session.
3. Await completion and run readiness checks.
4. Return participant-facing access information and an evaluator-only truth reference separately.
5. Collect relevant pre/post observations.
6. Stop, clean up, or restore the environment under an explicit lifecycle policy.

Record the real CORE session ID, snapshot hash, readiness results, and restoration method on each trial. Maintain a target lease across lifecycle operations and execution.

Verify reset coverage experimentally before enabling state-changing benchmark tasks. The adapter must distinguish “session restarted,” “scenario redeployed,” and “validated restoration”; these are not interchangeable guarantees.

No changes to CORE scenario logic are required for a first observational study. Multi-scenario evaluation can deploy a suite of separately frozen scenarios on the same CORE VM, one at a time.

## 15. Proposed user experience

Add an **Experiments** page with a wizard:

1. Select a task/scenario suite and its split.
2. Select an artifact snapshot or frozen artifact set.
3. Choose conditions, models, supported generation settings, repetitions, and budgets.
4. Review environment lifecycle and operator-interaction policies.
5. Preview the full schedule and estimated workload.
6. Start, pause between trials, inspect failures, and export results.

Add **Repeat / Compare** to saved prompts and generated artifacts. A saved-prompt action can create a development task and a pre-prompt checkpoint when one exists. It must not silently classify a previously seen task as held out.

Result views should include overall and per-task success, cost, reliability, regressions, individual verifier checks, and first-divergence links. Display whether each result is live execution, evidence-only evaluation, or recording playback.

A comparison should remain traceable from a summary statistic to the task, trial, effective model request, tool output, and verifier evidence that produced it.

## 16. Reproducibility package and paper outputs

Export a versioned package containing:

- Frozen experiment specification and randomized schedule.
- Participant-facing task prompts and separately controlled evaluator definitions.
- Scenario manifests, reproduction assets where distributable, and version identifiers.
- Artifact snapshots and generation/repair lineage.
- Model configuration, provider capabilities, and available server/model identifiers.
- Trial outcomes, attempts, raw usage, intervention records, and environment checks.
- Raw traces and evidence with credentials and unrelated sensitive data removed.
- Verifier code, analysis code, dependencies, and commands to reproduce tables and figures.
- Missing-data flags, failure dispositions, exclusions, and deviations from the original protocol.

Some secrets and answer keys may require restricted distribution. Record their role and access rules without placing them in participant-visible bundles.

Recommended paper outputs:

1. Main table: verified success by condition, with paired effect sizes and uncertainty.
2. Success versus total execution cost plot.
3. Per-task or per-family improvement/regression plot.
4. Reliability results across repetitions.
5. Guidance/tool ablation results.
6. Transfer results by scenario partition.
7. Generation-cost and failure analysis when claiming generation efficacy.

These are planned outputs; no result values should be filled in until the study is run.

## 17. Implementation and study phases

### Phase 1: Evaluation foundation

Implement task files, frozen conditions, isolated sequential trials, budgets, pre-prompt checkpoints, basic verifiers, required telemetry, and JSON/CSV export. Use one fixed CORE scenario and a small observational development suite.

Acceptance criterion: a frozen artifact can be evaluated with and without availability, every outcome links to verifier evidence, and failures remain visible in the exported dataset.

### Phase 2: Controlled artifact comparisons

Add independent tool/guidance conditions, supported seed controls, repeat scheduling, first-divergence inspection, nested-operation accounting, and paired analysis. Validate that condition membership is enforced at runtime.

Acceptance criterion: tool-only and guidance-only trials are demonstrably distinct, and repeated trials do not inherit earlier answers, process state, or shared artifact edits.

### Phase 3: Multi-scenario integration

Add the ScenarioForge adapter, frozen scenario suites, target locking, readiness records, and tested lifecycle handling. Establish scenario-family splits and evaluator-only truth storage.

Acceptance criterion: run a suite across several frozen scenarios with auditable identity, readiness, and task/scenario/condition linkage.

### Phase 4: Confirmatory study

Freeze hypotheses, artifact versions, test tasks, verifiers, budgets, exclusion rules, and analysis code. Use the pilot to finalize sample size. Run the held-out experiment without tuning on its results.

Acceptance criterion: reproduce the reported tables and figures from the exported package and document every deviation from the frozen protocol.

### Phase 5: Extensions

Add multiple-model replication, a study of the artifact-generation process, broader scenario-family transfer, and state-changing tasks only after restoration is validated. Add recorded-evidence modes for mechanism analysis without confusing them with live-environment success.

## 18. Threats to validity

| Threat | Mitigation and remaining limitation |
| --- | --- |
| Answer leakage from generation traces or facilitator material | Split development/test material, audit lineage, and separate evaluator data |
| Selecting only successful artifacts | Account for all candidates and selection costs when evaluating generation |
| Changing model/server behavior | Record versions and available identity metadata; avoid unsupported determinism claims |
| Scenario carryover | Observational primary suite or validated restoration; randomization alone is insufficient |
| Tool-call count compression | Measure underlying work and total resource use |
| Unused or truncated guidance | Log effective content and activation, and retain availability-based primary analysis |
| Hidden human help | Standardize policy, log interventions, and identify assisted outcomes |
| Pseudoreplication | Model task/scenario/lineage grouping and avoid treating seeds or turns as new scenarios |
| Verifier bias or incompleteness | Independent checks, known-good/bad tests, blinded review where needed, and version freeze |
| Infrastructure failures or missing telemetry | Predefined dispositions, durable attempts, complete reporting, and explicit unknown values |
| Overgeneralization from one environment | State scope clearly and add held-out scenario families for transfer claims |
| Post hoc metric selection | Predeclare primary endpoint and contrast; label exploratory analyses |

## 19. Immediate decisions before implementation

Agree on:

- The first artifact and observational task family.
- Whether the initial goal is a within-scenario case study or multi-scenario transfer.
- The primary success definition and budget.
- How the artifact was generated and which tasks must therefore remain development-only.
- The first model/backend and its supported generation controls.
- Whether any operator assistance is permitted.
- Whether equivalent environment restoration is available or the study will remain observational.
- Which resources must be measured directly and which will remain unavailable.

The first deliverable should be one complete, traceable paired experiment, not a large dashboard backed by incomplete measurement.

## 20. Research references

The design above is a proposed adaptation for CyberAgentFlow and ScenarioForge. The following sources motivate specific evaluation practices; they do not establish outcomes for this system.

1. **SkillsBench: Benchmarking How Well Agent Skills Work Across Diverse Tasks.** Version 4, June 2026. Paired evaluation with and without skills and deterministic task verification. [Paper](https://arxiv.org/abs/2602.12670v4).
2. **AI Agents That Matter.** Kapoor et al., 2024. Cost-aware agent evaluation, held-out evaluation, and reproducibility concerns. [Paper](https://arxiv.org/abs/2407.01502).
3. **τ-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains.** Yao et al., 2024. Outcome-based verification and repeated-trial reliability through pass^k. [Paper](https://arxiv.org/abs/2406.12045).
4. **Evaluating AGENTS.md: Are Repository-Level Context Files Helpful for Coding Agents?** Gloaguen et al., 2026. Evidence that additional context can have costs and negative effects, motivating ablations and regression reporting. Its coding-agent findings should not be assumed to transfer quantitatively to cybersecurity tasks. [Paper](https://arxiv.org/abs/2602.11988).
5. **Ollama Modelfile Reference.** Generation parameters, including seed. [Documentation](https://docs.ollama.com/modelfile#valid-parameters-and-values).
6. **OpenAI Chat Completions API Reference.** Best-effort seed behavior and backend determinism limitations; verify availability for the selected model/API. [Documentation](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create).

Local implementation sources reviewed for this plan include CyberAgentFlow's `mcp_client.py`, `session_logger.py`, `durable_event_store.py`, `app.py`, artifact storage/validation code, and ScenarioForge's README, CLI workflow, provisioning utilities, and CORE lifecycle/artifact-check routes. Reconfirm capabilities against the code revisions frozen for the actual study.
