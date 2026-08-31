# Data and Result Provenance

## Source classification

Every committed telemetry row is synthetic. No field-flight, HIL, SITL, company, customer, or third-party dataset is included.

The generator uses a versioned scenario definition, fixed integer seed, sample period, and policy. The pipeline writes each CSV and then reads it back before replay, so the evaluated input is the same byte sequence listed in the manifest.

## Two linked manifests

[`data/generated/manifest.json`](../data/generated/manifest.json) records:

- generator and schema version;
- SHA-256 and byte size for the policy, assurance case, STPA-informed model, benchmark configuration, `pyproject.toml`, and every package source file;
- path, scenario, seed, row count, byte size, SHA-256, and an explicit synthetic-data label for all 70 traces.

[`results/result_manifest.json`](../results/result_manifest.json) records SHA-256 and byte size for:

- the per-run CSV;
- representative state/action transitions;
- the JSON summary;
- Markdown report and SVG dashboard;
- all seven representative per-frame timelines.

The result manifest stores the data-manifest hash. The summary also stores that hash, so the reported metrics, result set, source/configuration set, and trace set are checked as one byte-level chain.

This is not cryptographic attestation: the manifests are not signed, a result manifest cannot authenticate its own metadata, and a repository maintainer can regenerate the chain. The Git commit is the external version anchor. The manifests make accidental staleness, partial regeneration, and unreviewed byte changes visible in tests and CI.

## Trace schema

| Field | Meaning | Unit/type |
|---|---|---|
| `scenario_id` | Scenario identifier | string |
| `fault` | Injected fault family | string |
| `run_id` | Scenario and seed identifier | string |
| `seed` | Deterministic generator seed | integer |
| `timestamp_s` | Replay time, strictly increasing | seconds |
| `localization_confidence` | Synthetic estimator confidence | ratio |
| `lidar_age_ms` | Age of latest LiDAR observation | ms |
| `cross_modal_consistency` | Synthetic camera–LiDAR agreement | ratio |
| `obstacle_distance_m` | Synthetic nearest-obstacle distance | m |
| `speed_mps` | Synthetic vehicle speed | m/s |
| `comm_age_ms` | Age of latest supervisory message | ms |
| `fallback_available` | Reported availability of a fallback path | boolean |
| `fault_active` | Whether the configured injection has begun | boolean |
| `scenario_oracle_positive` | Whether separately configured synthetic scenario criteria are positive | boolean |

The last field is intentionally not named ground truth. Four oracle thresholds differ from detector thresholds; stopping margin and fallback availability share their detector boundary. All remain functions of the same generated signals.

## Verification contract

Before regeneration, `runtime-assurance verify --root .` checks:

1. exact source-file coverage, hashes, and byte sizes;
2. exact generated-trace coverage, hashes, byte sizes, and row counts;
3. path containment inside the project;
4. summary and result-manifest binding to the current data manifest;
5. exact result-file coverage, hashes, and byte sizes.

`runtime-assurance benchmark --root .` then regenerates canonical LF-delimited traces and results. A second verification checks the regenerated chain, and CI requires no diff under `data/generated` or `results`.

The hashes identify exact bytes. They do not prove realism, authorship, sensor calibration, model correctness, independent labeling, or external validity. Operational logs would need additional provenance such as vehicle and sensor identifiers, firmware, configuration, clock source, coordinate/frame conventions, calibration state, operator, collection time, permissions, and a defensible reference system.
