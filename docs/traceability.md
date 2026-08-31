# UCA-to-Evidence Traceability

This table follows the executable links stored in the model and case files. The linter validates identifiers and coverage; the table explains their intended meaning.

| Loss | Hazard | Unsafe control action | Constraint | Leaf claim | Declared assumptions | Evidence / monitor | Failure recommendation | Fixture | Coverage |
|---|---|---|---|---|---|---|---|---|---|
| `L-1` | `H-1` insufficient modeled stopping separation | `UCA-1` recommends `CONTINUE` after the margin monitor has latched failure | `SC-1` | `C-SEPARATION` | `A-TELEM`, `A-CLOCK`, `A-BRAKE` | `E-OBS-MARGIN` / `M-OBS-MARGIN` | `HOVER` | `obstacle_intrusion` | Predicate and recommendation implemented; braking assumption and physical response unvalidated |
| `L-1`, `L-3` | `H-2` autonomy relies on inadequate localization/perception evidence | `UCA-2` recommends `CONTINUE` after a mapped evidence monitor has latched failure | `SC-2` | `C-STATE` | `A-TELEM`, `A-CLOCK`, `A-SCORES` | `E-LOC` / `M-LOC` | `HOVER` | `localization_drift` | Predicate and recommendation implemented; score calibration unvalidated |
| `L-1`, `L-3` | `H-2` | `UCA-2` | `SC-2` | `C-STATE` | `A-TELEM`, `A-CLOCK`, `A-SCORES` | `E-LIDAR-FRESH` / `M-LIDAR-FRESH` | `HOVER` | `lidar_dropout` | Predicate and recommendation implemented; time basis unvalidated |
| `L-1`, `L-3` | `H-2` | `UCA-2` | `SC-2` | `C-STATE` | `A-TELEM`, `A-CLOCK`, `A-SCORES` | `E-XMODAL` / `M-XMODAL` | `HOVER` | `cross_modal_disagreement` | Predicate and recommendation implemented; score calibration unvalidated |
| `L-2`, `L-3` | `H-3` mission mode requires a fresh link while link evidence is stale | `UCA-3` applies `CONTINUE` too long | `SC-3` | `C-LINK` | `A-CLOCK`, `A-LINK` | `E-COMM-FRESH` / `M-COMM-FRESH` | `RETURN_HOME` | `communication_loss` | Predicate and recommendation implemented; link-mode relevance and vehicle response unvalidated |
| `L-1`, `L-2`, `L-3` | `H-4` continuation requires a fallback reported unavailable | `UCA-4` applies `CONTINUE` too long | `SC-4` | `C-FALLBACK` | `A-FALLBACK` | `E-FALLBACK` / `M-FALLBACK` | `ABORT` | `compound_failure` | Reported availability and recommendation implemented; delivery and effectiveness out of scope |

## What validation actually proves

`runtime-assurance validate --root .` checks that:

- every control-structure edge resolves to declared components;
- every hazard links to losses;
- every UCA links to hazards and a declared control action;
- every UCA is controlled by at least one hazard-consistent constraint;
- every UCA appears in at least one causal scenario;
- every constraint is covered by a reachable leaf claim;
- every leaf claim names evidence, a constraint, and an assumption;
- every policy monitor has exactly one evidence mapping;
- every assumption is used and every non-goal is explicit;
- claim cycles, orphan evidence, duplicate identifiers, and unknown references are rejected.

The benchmark adds behavioral checks for expected monitor activation, exact action selection by the declared trigger monitor, response time, unexpected activation, overreaction, post-selection underreaction, and pre-injection intervention.

Together these checks establish internal structural and executable traceability. They do not prove STPA completeness, claim sufficiency, assumption validity, physical action delivery, or recovery effectiveness.
