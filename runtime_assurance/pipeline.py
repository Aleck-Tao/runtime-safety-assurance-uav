from __future__ import annotations

from pathlib import Path
from typing import Any

from .assurance_case import validate_assurance_case
from .config import load_policy, read_json, write_json
from .evaluation import RunMetrics, replay_trace, summarize_runs
from .reporting import (
    sha256_file,
    write_csv,
    write_jsonl,
    write_markdown_report,
    write_svg_dashboard,
)
from .simulation import BenchmarkDefinition, generate_trace, load_benchmark, read_trace, write_trace


RUN_FIELDS = list(RunMetrics.__dataclass_fields__)

TRANSITION_FIELDS = [
    "run_id",
    "timestamp_s",
    "argument_support_state",
    "action",
    "top_claim_support",
    "warning_monitors",
    "failed_monitors",
    "action_source_monitors",
    "affected_constraint_ids",
    "affected_hazard_ids",
]


def _benchmark_checks(
    summaries: list[dict[str, Any]], benchmark: BenchmarkDefinition
) -> list[dict[str, Any]]:
    scenarios = {scenario.id: scenario for scenario in benchmark.scenarios}
    checks: list[dict[str, Any]] = []
    for item in summaries:
        scenario_id = str(item["scenario_id"])
        scenario = scenarios[scenario_id]
        common = [
            {
                "id": "no-pre-injection-intervention",
                "scenario_id": scenario_id,
                "passed": item["mean_pre_injection_intervention_rate"] == 0.0,
                "criterion": "mean pre-injection intervention rate equals 0",
            },
            {
                "id": "no-unexpected-monitor-activation",
                "scenario_id": scenario_id,
                "passed": item["unexpected_monitor_activation_rate"] == 0.0,
                "criterion": "no monitor outside the declared scenario mapping latches failure",
            },
        ]
        checks.extend(common)
        if scenario.fault == "none":
            checks.append(
                {
                    "id": "baseline-exact-continue",
                    "scenario_id": scenario_id,
                    "passed": item["maximum_actions"] == ["CONTINUE"],
                    "criterion": "maximum selected action is exactly CONTINUE",
                }
            )
            continue
        checks.extend(
            [
                {
                    "id": "expected-monitor-activation",
                    "scenario_id": scenario_id,
                    "passed": item["expected_monitor_activation_rate"] == 1.0,
                    "criterion": "all scenario-mapped monitors latch failure in every seed",
                },
                {
                    "id": "support-loss-event",
                    "scenario_id": scenario_id,
                    "passed": item["support_loss_detection_rate"] == 1.0,
                    "criterion": "argument support becomes UNSUPPORTED in every seed",
                },
                {
                    "id": "assurance-response-time",
                    "scenario_id": scenario_id,
                    "passed": item["p95_assurance_response_time_s"] is not None
                    and item["p95_assurance_response_time_s"] <= 0.5,
                    "criterion": "p95 support-loss response relative to synthetic oracle <= 0.5 s",
                },
                {
                    "id": "exact-action-selection",
                    "scenario_id": scenario_id,
                    "passed": item["exact_expected_action_rate"] == 1.0
                    and item["maximum_actions"] == [scenario.expected_action],
                    "criterion": f"every seed selects exact action {scenario.expected_action} without a more severe maximum",
                },
                {
                    "id": "policy-response-time",
                    "scenario_id": scenario_id,
                    "passed": item["p95_policy_response_time_s"] is not None
                    and item["p95_policy_response_time_s"] <= 0.5,
                    "criterion": "p95 exact-action response from trigger raw failure <= 0.5 s",
                },
                {
                    "id": "bounded-time-at-risk",
                    "scenario_id": scenario_id,
                    "passed": item["mean_time_at_risk_before_expected_action_s"] is not None
                    and item["mean_time_at_risk_before_expected_action_s"] <= 0.5,
                    "criterion": "mean positive-oracle time before exact expected action <= 0.5 s",
                },
                {
                    "id": "no-overreaction",
                    "scenario_id": scenario_id,
                    "passed": item["overreaction_run_rate"] == 0.0,
                    "criterion": "no action more severe than the declared expected action is selected",
                },
                {
                    "id": "maintain-exact-action-while-oracle-positive",
                    "scenario_id": scenario_id,
                    "passed": item["post_selection_underreaction_run_rate"] == 0.0,
                    "criterion": "after first exact selection, no lower-priority action appears while the synthetic oracle remains positive",
                },
            ]
        )
    return checks


def _source_files(root: Path, primary: list[Path]) -> list[Path]:
    files = [*primary, root / "pyproject.toml"]
    files.extend(sorted((root / "runtime_assurance").rglob("*.py")))
    resolved: list[Path] = []
    for path in files:
        candidate = path.resolve()
        if not candidate.is_relative_to(root):
            raise ValueError(f"Benchmark source escapes project root: {candidate}")
        if not candidate.is_file():
            raise FileNotFoundError(candidate)
        resolved.append(candidate)
    return sorted(set(resolved), key=lambda path: path.relative_to(root).as_posix())


def _result_manifest(root: Path, result_paths: list[Path], data_manifest_path: Path) -> dict[str, Any]:
    entries = []
    for path in sorted(result_paths, key=lambda item: item.relative_to(root).as_posix()):
        entries.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return {
        "schema_version": "1.0",
        "generated_by": "runtime_assurance.pipeline.run_benchmark",
        "generator_version": "0.1.0",
        "data_manifest_sha256": sha256_file(data_manifest_path),
        "result_count": len(entries),
        "results": entries,
    }


def run_benchmark(
    root: Path,
    policy_path: Path | None = None,
    case_path: Path | None = None,
    stpa_path: Path | None = None,
    benchmark_path: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    policy_path = (policy_path or root / "config" / "assurance_policy.json").resolve()
    case_path = (case_path or root / "assurance_case" / "uav_runtime_case.json").resolve()
    stpa_path = (stpa_path or root / "hazards" / "stpa_model.json").resolve()
    benchmark_path = (benchmark_path or root / "experiments" / "benchmark_config.json").resolve()

    policy = load_policy(policy_path)
    assurance_case = read_json(case_path)
    stpa_model = read_json(stpa_path)
    validate_assurance_case(assurance_case, stpa_model, policy)
    benchmark = load_benchmark(benchmark_path, policy)

    trace_entries: list[dict[str, Any]] = []
    run_metrics: list[RunMetrics] = []
    representative_transitions: list[dict[str, Any]] = []
    traces_root = root / "data" / "generated" / "traces"
    timelines_root = root / "results" / "case_timelines"
    timeline_paths: list[Path] = []

    for scenario in benchmark.scenarios:
        for seed in benchmark.seeds:
            trace_path = traces_root / scenario.id / f"seed-{seed}.csv"
            generated_rows = generate_trace(scenario, seed, benchmark, policy)
            write_trace(trace_path, generated_rows)
            rows = read_trace(trace_path)
            replay = replay_trace(
                rows,
                policy,
                assurance_case,
                stpa_model,
                scenario.expected_monitor_ids,
                scenario.action_trigger_monitor_id,
                scenario.expected_action,
            )
            run_metrics.append(replay.metrics)
            trace_entries.append(
                {
                    "path": trace_path.relative_to(root).as_posix(),
                    "scenario_id": scenario.id,
                    "seed": seed,
                    "rows": len(rows),
                    "bytes": trace_path.stat().st_size,
                    "sha256": sha256_file(trace_path),
                    "provenance": "deterministically generated telemetry; no SITL, HIL, or flight data",
                }
            )
            if seed == benchmark.representative_seed:
                representative_transitions.extend(replay.transition_rows)
                timeline_rows = []
                for row, snapshot in zip(rows, replay.snapshots, strict=True):
                    timeline_rows.append(
                        {
                            "run_id": row["run_id"],
                            "scenario_id": row["scenario_id"],
                            "fault_active": row["fault_active"] == "true",
                            "scenario_oracle_positive": row["scenario_oracle_positive"] == "true",
                            "case": snapshot.to_dict(),
                        }
                    )
                timeline_path = timelines_root / f"{scenario.id}.jsonl"
                write_jsonl(timeline_path, timeline_rows)
                timeline_paths.append(timeline_path)

    expected_timelines = {path.resolve() for path in timeline_paths}
    if timelines_root.is_dir():
        for stale_path in timelines_root.glob("*.jsonl"):
            if stale_path.resolve() not in expected_timelines:
                stale_path.unlink()

    source_files = _source_files(
        root, [policy_path, case_path, stpa_path, benchmark_path]
    )
    manifest = {
        "schema_version": "1.1",
        "generated_by": "runtime_assurance.pipeline.run_benchmark",
        "generator_version": "0.1.0",
        "source_files": [
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in source_files
        ],
        "trace_count": len(trace_entries),
        "traces": trace_entries,
    }
    manifest_path = root / "data" / "generated" / "manifest.json"
    write_json(manifest_path, manifest)

    runs_path = root / "results" / "benchmark_runs.csv"
    transitions_path = root / "results" / "representative_transitions.csv"
    summary_path = root / "results" / "benchmark_summary.json"
    report_path = root / "results" / "benchmark_report.md"
    dashboard_path = root / "results" / "benchmark_dashboard.svg"
    write_csv(runs_path, RUN_FIELDS, [item.to_dict() for item in run_metrics])
    write_csv(
        transitions_path,
        TRANSITION_FIELDS,
        representative_transitions,
    )
    summaries = summarize_runs(run_metrics)
    checks = _benchmark_checks(summaries, benchmark)
    summary = {
        "schema_version": "1.1",
        "scope": "deterministic synthetic telemetry replay, fixed claim-state updates, and fallback recommendation; not physical-flight validation",
        "support_semantics": "SUPPORTED means all persistence-qualified monitor conditions in the fixed top claim remain in their pass state under declared assumptions; it is not a physical-safety classification",
        "declared_assumptions": [
            {
                "id": str(item["id"]),
                "validation_status": str(item["validation_status"]),
            }
            for item in assurance_case["assumptions"]
        ],
        "oracle_interpretation": "separately configured synthetic scenario criteria; not independent ground truth",
        "run_count": len(run_metrics),
        "scenario_count": len(benchmark.scenarios),
        "seeds_per_scenario": len(benchmark.seeds),
        "sample_period_s": benchmark.sample_period_s,
        "duration_s": benchmark.duration_s,
        "data_manifest_sha256": sha256_file(manifest_path),
        "scenarios": summaries,
        "benchmark_checks": checks,
        "all_benchmark_checks_passed": all(bool(item["passed"]) for item in checks),
    }
    write_json(summary_path, summary)
    write_markdown_report(report_path, summaries)
    write_svg_dashboard(dashboard_path, summaries)

    result_paths = [
        runs_path,
        transitions_path,
        summary_path,
        report_path,
        dashboard_path,
        *timeline_paths,
    ]
    result_manifest_path = root / "results" / "result_manifest.json"
    write_json(result_manifest_path, _result_manifest(root, result_paths, manifest_path))
    return summary
