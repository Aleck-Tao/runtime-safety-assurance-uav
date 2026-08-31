# Runtime Assurance Benchmark

All inputs are deterministically generated telemetry traces. This is an open-loop regression fixture, not field-flight validation.
All six declared case assumptions remain UNVALIDATED; support labels are conditional predicate results.

| Scenario | Runs | Expected monitors | Support-loss event | Exact action | p95 policy response | First 1 s oracle coverage | Pre-oracle intervention | Maximum action |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| baseline | 10 | n/a | n/a | n/a | n/a s | n/a | n/a | CONTINUE |
| localization_drift | 10 | 1.000 | 1.000 | 1.000 | 0.200 s | 1.000 | 0.609 | HOVER |
| lidar_dropout | 10 | 1.000 | 1.000 | 1.000 | 0.200 s | 1.000 | 0.571 | HOVER |
| cross_modal_disagreement | 10 | 1.000 | 1.000 | 1.000 | 0.200 s | 0.990 | 0.582 | HOVER |
| obstacle_intrusion | 10 | 1.000 | 1.000 | 1.000 | 0.200 s | 0.800 | 0.125 | HOVER |
| communication_loss | 10 | 1.000 | 1.000 | 1.000 | 0.200 s | 1.000 | 0.692 | RETURN_HOME |
| compound_failure | 10 | 1.000 | 1.000 | 1.000 | 0.200 s | 0.900 | 0.600 | ABORT |

The scenario oracle uses separately configured synthetic criteria. It reduces direct threshold identity for four signal families but is not independent ground truth. Oracle-positive coverage is descriptive and is not an acceptance gate.

Policy response time begins at the action-trigger monitor's first raw failure and ends only when the exact expected action is selected. More severe but incorrect actions do not count as success. Neither timing metric includes command delivery, actuator response, or vehicle recovery.

The p95 value uses the nearest-rank definition across seeds.
