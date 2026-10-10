# Thresholds, persistence and short events

The original 70-trace benchmark tests sustained faults. This study asks what changes when faults are brief, noisy, or recover before the next occurrence. It uses the existing supervisor, claim graph and action priorities, without changing their implementation.

There are 40 generated input traces: two signal families, four profiles and five seeds. Each is replayed under nine policies (`failure_samples=1,3,5` and three thresholds), giving 360 runs. The 80 oracle events are assessed under nine policies: the 720 event rows are paired evaluations, not 720 independent fault realizations. [Configuration](../experiments/persistence_study.json) fixes the oracle separately from the swept monitor threshold.

| Profile | Construction at 10 Hz |
|---|---|
| Short pulses | Four events lasting 1, 2, 3 and 5 samples, with clear recovery gaps |
| Boundary noise | Eight seconds close to monitor failure thresholds but outside the oracle-positive region |
| Repeated recovery | Three one-second faults separated by six good samples |
| Slow ramp | A two-second ramp into a sustained fault, followed by recovery |

Localization failure thresholds are `0.50/0.55/0.60`, with oracle confidence `<=0.45`. Obstacle-margin thresholds are `-0.10/0.00/0.20 m`, with oracle margin `<=0 m`. The negative obstacle threshold is an intentionally late comparison, not a recommended operating point. Warning persistence stays at two samples and recovery at five. Every assessment uses the same 150-sample window; other sensors remain in their passing ranges.

## Observed tradeoff

| Failure samples | Short-event recall, either family | Delay for detected short events | Unmatched localization hover episodes at threshold 0.55 |
|---:|---:|---:|---:|
| 1 | 100% | 0.0 s | 25 |
| 3 | 50% | 0.2 s | 4 |
| 5 | 25% | 0.4 s | 0 |

Short-event recall uses 20 events per family/threshold across five seeds. The last column uses five boundary-noise traces with no oracle-positive event. A longer persistence window rejects more noise, but also misses short faults. These constructed traces make that tradeoff measurable; they do not establish the best setting for an aircraft.

Threshold choice adds a second tradeoff. At the more conservative localization threshold `0.60`, all three persistence settings produce five unmatched hover episodes, with respectively `41.8/40.3/38.5 s` of oracle-negative hover-or-higher action across five traces. At threshold `0.55` with one-sample failure, there are more separate episodes (25) but only `30.4 s` of such action. Episode counts and duration must therefore be read together: fewer starts can simply mean that the supervisor stays in hover longer.

For obstacle ramps with five-sample persistence, the maximum observed oracle-to-action delay is `0.5/0.4/0.2 s` at thresholds `-0.10/0.00/0.20 m`. All repeated-recovery events are detected, and the five lower-severity recovery samples give a `0.4 s` delay from the first healthy sample. These timings end at a recommendation; the original open-loop scope still applies.

## Event definitions and reproducibility

An event is a contiguous run of oracle-positive samples. Detection requires `HOVER` or a higher-priority action while the event is active; `SLOW` is retained in the transition table but is not counted as detection. Missed events retain a null delay and remain in the recall denominator. If an action starts before the oracle event, its signed onset offset is negative and its detection delay is zero.

An unmatched action episode is a contiguous hover-or-higher episode overlapping no oracle event. Oracle-negative action samples also include anticipation and recovery after a matched event, so they are reported separately. Neither quantity estimates real-world false-alarm prevalence. Recovery is evaluated before the next oracle event; a missing recovery or an event cut by the assessment boundary is explicitly marked as censored.

The study reports event recall and trigger delay rather than full-horizon positive-sample coverage. Tests verify that appending quiet samples cannot dilute the fixed-window results, and extending a positive tail does not improve detection delay or recall. Raw inputs, all policy/event rows and every action/status/oracle transition are committed:

- [Inputs](../studies/persistence/telemetry.csv) and [transitions](../studies/persistence/transitions.csv).
- [Per-run metrics](../studies/persistence/runs.csv), [events](../studies/persistence/events.csv) and [grouped summary](../studies/persistence/summary.json).
- [Manifest](../studies/persistence/manifest.json) binding source files, configuration and output hashes.

```bash
runtime-assurance persistence-study --root .          # regenerate
runtime-assurance persistence-study --root . --check  # verify hashes and fresh byte-for-byte replay
```

CI checks the old benchmark and this study on Linux/Windows and Python 3.11–3.13. Scheduled replay is Monday at 01:41 UTC; manual dispatch is also available.
