# Timing and stopping-margin analysis

This note interprets the committed [benchmark summary](../results/benchmark_summary.json) and [transition table](../results/representative_transitions.csv). The parameter sensitivities are analytical consequences of the current policy; they are not results from a new benchmark sweep.

## Why all six fault scenarios report 0.20 seconds

The experiment samples every `Delta_t = 0.1 s`. With `N = 3` consecutive failures required, a sustained failure first observed at sample `k` latches at sample `k+2`. The delay from the first observed failure is therefore

```text
delay = (N - 1)*Delta_t = 0.2 s.
```

The identical p95 values across scenarios mostly confirm this shared state-machine rule. They do not show that different physical faults have equally fast end-to-end responses. The measurement begins with the first raw failing sample, so it excludes any delay from a real event to that sample, and ends before command delivery or vehicle response.

The stopping calculation assigns `0.5 s` to response, leaving `0.3 s` after the current persistence delay for downstream response. Under uniform sampling, increasing the failure window to five samples would raise the observed decision delay to `0.4 s` and leave `0.1 s` within that same budget. This is a model calculation, and shows why persistence should be tuned together with the response budget. Irregular sampling would require reasoning about elapsed time rather than sample count alone.

## The denominator changes the apparent result

In obstacle intrusion, the synthetic oracle and stopping monitor use the same zero-margin boundary. Two positive-oracle samples arrive before failure latches. The trace contains 384 oracle-positive samples, so full-horizon coverage is

```text
(384 - 2) / 384 = 99.4792%.
```

In the first one-second window there are ten samples, giving

```text
(10 - 2) / 10 = 80%.
```

Both describe the same reaction. Extending the post-fault trace increases the first percentage without changing the decision. Event delay and fixed-window coverage therefore provide a clearer view of early behavior.

For four signal families, the oracle threshold is more severe than the monitor failure threshold. Localization, for example, fails the monitor at confidence `0.55`, while its oracle turns positive at `0.45`. Early recommendations during the ramp are consequently expected. Across seeds, the first intervention precedes the oracle by a mean `0.78 s` for localization and `0.90 s` for communication. These durations characterize threshold conservatism in the constructed ramps; they do not estimate the frequency of unnecessary interventions in ordinary operation.

## Stopping-margin sensitivity

With distance `D`, speed `v`, clearance `c`, response budget `T`, and deceleration lower bound `a`, the model is

```text
m = D - c - v*T - v^2/(2*a).
```

Its local sensitivities are

```text
dm/dD = 1
dm/dv = -T - v/a
dm/dT = -v
dm/da = v^2/(2*a^2).
```

At an illustrative `v = 5 m/s` with the configured `T = 0.5 s` and `a = 2.5 m/s^2`, each additional `0.1 s` of response budget requires another `0.5 m` of distance to preserve the margin. Raising speed from `5` to `6 m/s` requires an additional

```text
0.5*(6-5) + (6^2-5^2)/(2*2.5) = 2.7 m.
```

These are substitutions into the model, not measured vehicle behavior. They show why calibrating a stopping monitor requires both the braking assumption and the complete response path. The pass threshold additionally requires `m >= 1.5 m`, on top of the `1.5 m` clearance already subtracted inside `m`.

## Why the compound trace is useful

For seed 101, the compound scenario selects `SLOW` at `20.2 s`, `HOVER` at `20.6 s`, and `ABORT` at `20.8 s`. The claim is already `UNSUPPORTED` at the intermediate hover stage, yet the action still has to escalate when fallback evidence fails. A binary supported/unsupported check alone would miss an action policy stuck at `HOVER`.

The benchmark consequently checks the expected action, its source monitor, excessive escalation, and later downgrade separately. This examines the interaction between evidence propagation and recommendation priority. Since replay is open-loop, these checks establish the selected recommendation; the continuing obstacle-margin violations make the remaining need for closed-loop fallback evaluation concrete.
