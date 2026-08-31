# Decision Log

This record captures decisions made while building and reviewing the initial public prototype on 2026-08-31. It is not a reconstruction of earlier research activity.

## D-001: One bounded question

The project asks whether a fixed, hazard-linked claim graph can update from replayed telemetry and produce reproducible fallback recommendations. Perception, control, vehicle integration, and physical recovery remain outside the implemented boundary.

## D-002: STPA-informed, not “full STPA”

STPA concepts were selected because the prototype focuses on unsafe continuation recommendations and their relationship to evidence and fallback policy. Review showed that the initial single-component boundary was too narrow for physical losses, so the model now distinguishes a conceptual mission-system analysis boundary from the implemented supervisor boundary and uses a structured control graph.

The public wording is “bounded, STPA-informed supervisor model.” It does not claim complete UCA elicitation, risk-method breadth, or independent domain review.

## D-003: Small executable case, no standards-conformance claim

A compact JSON graph makes claims, assumptions, evidence, monitors, and constraints executable with the Python standard library. The representation is not labelled SACM- or GSN-compliant. The graph is fixed; only node support changes at runtime.

## D-004: Rename ground truth to synthetic scenario oracle

The first implementation defined `ground_truth_unsafe` using monitor failure thresholds. That made the detector part of its own evaluation label. Four more-severe scenario criteria were introduced, while stopping margin and fallback availability retained the same boundary.

Review identified that “independent ground truth” was still too strong because both detector and oracle are deterministic functions of the same generated variables. The field is therefore `scenario_oracle_positive`, and all documentation calls it a separately configured synthetic oracle.

## D-005: Remove the horizon-biased acceptance gate

An early smoke test missed a `0.99 unsafe recall` gate because two persistence frames occupied a large fraction of a short post-fault window. Extending the smoke horizon made the score pass, but review correctly identified this as horizon bias: with a fixed initial delay, the fraction approaches one as more post-fault frames are appended.

Full-horizon coverage is now descriptive only. Release gates use an event, timestamped response, exact action, and bounded time at risk; the report also shows a fixed first-second coverage window. The short pipeline test no longer needs an artificially long horizon to satisfy a recall threshold.

## D-006: Open-loop replay cannot prove recovery

Fallback recommendations do not modify generated telemetry. The obstacle trace continues to contain non-positive stopping margins after `HOVER` is selected. This behavior is retained as a visible limitation and motivates a later closed-loop SITL experiment.

## D-007: Separate status persistence from action persistence

The first state machine keyed persistence only on status, so a latched `FAIL/HOVER` did not escalate when the same monitor began returning missing evidence with `FAIL/ABORT`. A first repair keyed on `(status, action)`, but adversarial review found the opposite problem: alternating ordinary and missing failures reset the pair on every frame and could leave the monitor at `PASS/CONTINUE` indefinitely.

The final state machine uses nested status counters and separate action counters. Consecutive `WARN or FAIL` samples latch warning, consecutive failure status latches failure regardless of action type, sustained higher-priority action evidence escalates separately, and downgrade requires the recovery window. Regression tests preserve both counterexamples.

## D-008: Claim support is not physical safety

The initial `SAFE/DEGRADED/UNSAFE` aggregate labels overstated what six telemetry predicates can establish. They were replaced by `SUPPORTED/DEGRADED/UNSUPPORTED`. The top claim is conditional on six machine-readable assumptions, all marked `UNVALIDATED`.

## D-009: Require exact action and expose early intervention

The first evaluator counted any action at least as severe as the expected action as success. That allowed an incorrect `ABORT` to pass a `HOVER` scenario. Evaluation now requires the exact action to be produced by the declared trigger monitor, rejects a more-severe maximum, records overreaction, identifies unexpected monitor activation, and rejects a later downgrade while the oracle remains positive.

The original “pre-fault alert” rate counted only frames before injection and hid conservative interventions during a fault ramp. The result now separates pre-injection intervention from pre-oracle intervention and reports the latter without calling it a false-positive rate.

## D-010: Bind source, traces, and results without claiming attestation

The initial manifest hashed four JSON inputs and generated traces but not evaluator code or outputs. The data manifest now covers package source and `pyproject.toml`; a linked result manifest covers every generated result artifact. Tamper tests modify a trace, a result, and a source file.

The manifests detect byte-level inconsistency. They are not signed and do not prove realism, authorship, or external validity.

## D-011: Publish one honest initial version

The initial repository is released as one synthetic, open-loop v0.1 rather than split or backdated to imitate a longer research history. Later commits should correspond to real additions—boundary/transient fixtures, irregular timing, SITL ingestion, closed-loop evaluation, or external review—and carry their own tests and evidence.
