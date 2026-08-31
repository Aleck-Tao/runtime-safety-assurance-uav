# Methodology

## 1. Analysis and implementation boundaries

This prototype uses selected STPA concepts—losses, system-level hazard states, unsafe control actions, constraints, a simplified control structure, and causal scenarios—to organize a bounded supervisor analysis. It is STPA-informed, not a complete system-level STPA. No operational design domain or airframe is declared, and the analysis has not undergone independent domain review.

The conceptual analysis boundary includes an operator/supervisory station, autonomy stack, runtime supervisor, flight controller, vehicle, sensing, and environment. The implemented boundary is much smaller: a telemetry evaluator, a fixed claim graph, a fallback recommendation policy, deterministic trace generation, and replay evaluation. Perception, state estimation, navigation, flight control, actuator dynamics, command transport, and the vehicle are not implemented.

This split keeps physical losses and system hazards at the conceptual system level without implying that the code models the whole system.

## 2. Bounded STPA-informed model

[`hazards/stpa_model.json`](../hazards/stpa_model.json) records the two boundaries and a structured component/edge control graph. Each unsafe control action contains one control action and one hazardous context. Each safety constraint names the UCAs it controls, and each UCA must also appear in a causal scenario.

The four UCAs are selected candidate unsafe continuation recommendations in predeclared evidence contexts. They are tightly coupled to the implemented supervisor predicates and are not presented as exhaustive UCA elicitation for an outdoor UAV system.

The linter enforces:

- valid control-structure endpoints and edge types;
- loss references from every hazard;
- hazard references from every UCA;
- explicit UCA and hazard references from every constraint;
- a shared hazard between a constraint and each referenced UCA;
- constraint coverage for every UCA and hazard;
- causal-scenario coverage for every UCA.

These checks establish structural completeness relative to the committed identifiers. They do not establish that the chosen losses, hazards, UCAs, constraints, or scenarios are sufficient.

## 3. Fixed assurance argument and support semantics

[`assurance_case/uav_runtime_case.json`](../assurance_case/uav_runtime_case.json) contains one conditional top claim and four leaf claims. Every policy monitor maps to exactly one evidence item. Each leaf claim names a safety constraint and at least one explicit assumption; every constraint must be covered by a leaf claim.

The top claim is deliberately narrow:

> Given the declared assumptions and telemetry processed through the current frame, all persistence-qualified monitor conditions required for continuation remain in their pass state.

Six assumptions are machine-readable and marked `UNVALIDATED`: telemetry fidelity, clock alignment, score calibration, the stopping-model bound, link-mode relevance, and truthful fallback availability. Seven non-goals are also stored with the case.

At each frame:

1. monitors evaluate raw evidence;
2. persistence logic updates latched monitor status and action separately;
3. evidence `PASS`, `WARN`, or `FAIL` propagates through the fixed `all` claim strategies;
4. the top result maps to `SUPPORTED`, `DEGRADED`, or `UNSUPPORTED`;
5. the highest-priority latched recommendation is selected;
6. non-pass leaf claims identify the affected constraints and hazards.

These labels describe argument support, not physical safety. Loss of support triggers a conservative recommendation; support does not validate the assumptions or establish safe flight.

| Output field | Values | Meaning |
|---|---|---|
| `observations.*.raw_status` | `PASS/WARN/FAIL` | Current predicate result before persistence |
| `observations.*.status` | `PASS/WARN/FAIL` | Latched monitor result after persistence |
| `claim_support`, `top_claim_support` | `PASS/WARN/FAIL` | Propagated support verdict inside the fixed graph |
| `argument_support_state` | `SUPPORTED/DEGRADED/UNSUPPORTED` | User-facing aggregate rendering of the top verdict |
| `affected_constraint_ids`, `affected_hazard_ids` | identifier lists | Traceability tags for non-pass leaf claims, not observations that a physical hazard has occurred |

The JSON graph borrows the familiar claim-support-evidence structure of assurance cases, but it is not SACM or GSN. The graph never restructures at runtime. There is no evidence lifecycle, change-impact analysis, governance workflow, or dynamic argument reconfiguration.

## 4. Monitor state machine and input handling

Numeric monitors have pass, warning, and failure bands. At the nominal 0.1 s sample period:

- two consecutive `WARN or FAIL` samples latch `WARN`;
- three consecutive `FAIL` samples latch `FAIL`;
- five consecutive lower-severity samples are required for status recovery;
- action upgrade and downgrade use separate persistence counters.

Separating status from action is important. Ordinary numeric failure may recommend `HOVER` while missing input recommends `ABORT`; alternating between them must not reset continuous failure status and leave the claim `SUPPORTED`. A more severe action still requires its own consecutive window, while downgrade requires the recovery window.

Boolean parsing accepts only booleans, integer `0/1`, or the strings `true/false/0/1`. Numeric parsing rejects booleans, missing values, strings that are not finite numbers, and all NaN or infinity forms. A non-finite derived result is converted to missing evidence and follows the fail-closed action. Policy loading also validates ordered actions:

```text
CONTINUE is globally lowest
warning_action <= failure_action <= missing_action
```

## 5. Stopping-margin model

The implemented derived metric is:

```text
margin = obstacle_distance
       - minimum_clearance
       - speed * response_time_budget
       - speed^2 / (2 * guaranteed_deceleration_lower_bound)
```

The versioned demonstrator parameters are:

- `minimum_clearance_m = 1.5`;
- `response_time_budget_s = 0.5`;
- `guaranteed_deceleration_lower_bound_mps2 = 2.5`.

“Guaranteed” is a model role, not an experimental finding: the bound is an unvalidated assumption. The 0.5 s budget is intended to include the 0.2 s persistence delay from first raw failure to a three-sample latch at 10 Hz plus 0.3 s assumed downstream allowance. The implementation does not measure transport, controller, actuator, or vehicle response, so the budget cannot be claimed complete for a physical platform.

The stopping-margin monitor passes at `>= 1.5 m`, warns between `0` and `1.5 m`, and fails at `<= 0 m`. Because the equation already subtracts the 1.5 m protected clearance, the pass threshold is an additional 1.5 m warning reserve.

## 6. Synthetic scenario oracle

An early draft used detector thresholds as its own `ground_truth_unsafe` label. That was circular. The committed trace field is now called `scenario_oracle_positive`, and the configuration describes a `scenario_oracle` rather than ground truth.

| Signal | Monitor failure | Scenario oracle |
|---|---:|---:|
| Localization confidence | `<= 0.55` | `<= 0.45` |
| LiDAR age | `>= 400 ms` | `>= 500 ms` |
| Cross-modal consistency | `<= 0.45` | `<= 0.35` |
| Communication age | `>= 1000 ms` | `>= 1200 ms` |
| Stopping margin | `<= 0.00 m` | `<= 0.00 m` |
| Fallback availability | unavailable | unavailable |

The first four criteria are more severe than the monitor failure thresholds, reducing direct threshold identity. The last two intentionally share the monitor boundary. All six remain deterministic functions of the same generated variables, so the oracle is not independent ground truth and cannot establish detector validity.

## 7. Benchmark metrics and gates

Seven 60 s scenarios are generated at 10 Hz for ten fixed seeds: one baseline plus localization drift, LiDAR dropout, cross-modal disagreement, obstacle intrusion, communication loss, and a compound failure. Each fault ramps after 20 s.

Per-run metrics include:

- first fault-injection and scenario-oracle timestamps;
- first raw failure of the declared action-trigger monitor;
- first `UNSUPPORTED` support state;
- first selection of the exact expected action by the declared trigger monitor;
- support-loss response relative to oracle onset;
- exact-action policy response relative to trigger raw failure;
- positive-oracle time before the exact action;
- expected and unexpected latched monitor sets;
- action overreaction frames;
- lower-priority action frames after the first exact selection while the oracle remains positive;
- intervention before injection and between injection and oracle onset;
- support coverage in the first second after oracle onset;
- full oracle-positive coverage as a descriptive per-run field.

The release gates require the expected monitor set, a support-loss event, the exact expected action, bounded response, no unexpected monitor activation, no more-severe maximum action, no overreaction after the trigger, no post-selection downgrade while the oracle remains positive, and no pre-injection intervention. A more severe action is not accepted as “at least as safe,” and a momentarily correct action cannot mask later underreaction.

Full-horizon frame coverage is not a gate. With a fixed persistence delay, extending the post-fault trace makes the fraction converge toward one without improving the detector. The fixed first-second window exposes this effect: obstacle intrusion reports 0.800 while its full 60 s descriptive coverage is 0.994792.

Pre-oracle intervention is also reported instead of being hidden inside a “pre-fault” statistic. It measures conservatism during the fault ramp but cannot be interpreted as a false-positive rate.

Nearest-rank p95 is used across the ten fixed seeds. A negative support-loss response means the claim became unsupported before the synthetic oracle criterion; it does not mean a physical hazard was predicted.

## 8. Reproducibility and interpretation limits

The data manifest hashes the four configuration/model inputs, `pyproject.toml`, every package source file, and all 70 generated traces. The result manifest hashes the summary, run table, transition table, report, dashboard, and representative timelines. Verification checks exact path coverage, hashes, byte sizes, trace row counts, path containment, and manifest bindings.

This is an integrity and reproducibility mechanism, not signed provenance. It cannot prove data realism, authorship, correct calibration, or external validity.

The current fixture lacks benign near-boundary cases, short transient faults, explicit recovery scenarios, and irregular sampling. It also lacks independently produced SITL/HIL/flight telemetry and closed-loop fallback behavior. Those are required before making claims about practical detector validity or recovery performance.
