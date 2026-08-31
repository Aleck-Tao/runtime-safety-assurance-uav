from __future__ import annotations

import csv
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import finite_float, read_json
from .models import AssurancePolicy
from .monitors import derive_metric


TRACE_COLUMNS = [
    "scenario_id",
    "fault",
    "run_id",
    "seed",
    "timestamp_s",
    "localization_confidence",
    "lidar_age_ms",
    "cross_modal_consistency",
    "obstacle_distance_m",
    "speed_mps",
    "comm_age_ms",
    "fallback_available",
    "fault_active",
    "scenario_oracle_positive",
]


@dataclass(frozen=True)
class ScenarioDefinition:
    id: str
    fault: str
    onset_s: float | None
    expected_monitor_ids: tuple[str, ...]
    action_trigger_monitor_id: str | None
    expected_action: str


@dataclass(frozen=True)
class BenchmarkDefinition:
    schema_version: str
    duration_s: float
    sample_period_s: float
    scenario_oracle: dict[str, float]
    representative_seed: int
    seeds: tuple[int, ...]
    scenarios: tuple[ScenarioDefinition, ...]


def _strict_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be an integer")
    numeric = finite_float(value, label)
    result = int(numeric)
    if numeric != result:
        raise ValueError(f"{label} must be an integer")
    return result


def load_benchmark(path: Path, policy: AssurancePolicy) -> BenchmarkDefinition:
    raw = read_json(path)
    duration_s = finite_float(raw["duration_s"], "duration_s")
    sample_period_s = finite_float(raw["sample_period_s"], "sample_period_s")
    if duration_s <= 0 or sample_period_s <= 0 or sample_period_s > duration_s:
        raise ValueError("Invalid benchmark duration or sample period")
    sample_count = duration_s / sample_period_s
    if not math.isclose(sample_count, round(sample_count), rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("duration_s must be an integer multiple of sample_period_s")

    scenario_oracle = {
        str(key): finite_float(value, f"scenario_oracle.{key}")
        for key, value in raw.get("scenario_oracle", {}).items()
    }
    required_oracle = {
        "comm_age_ms_min",
        "cross_modal_consistency_max",
        "lidar_age_ms_min",
        "localization_confidence_max",
        "stopping_margin_m_max",
    }
    if set(scenario_oracle) != required_oracle:
        raise ValueError(f"scenario_oracle must contain exactly {sorted(required_oracle)}")

    seeds = tuple(
        _strict_int(seed, f"seeds[{index}]")
        for index, seed in enumerate(raw.get("seeds", []))
    )
    if not seeds or len(seeds) != len(set(seeds)):
        raise ValueError("Benchmark seeds must be non-empty and unique")
    representative_seed = _strict_int(raw["representative_seed"], "representative_seed")
    if representative_seed not in seeds:
        raise ValueError("representative_seed must appear in seeds")

    scenarios: list[ScenarioDefinition] = []
    seen_ids: set[str] = set()
    supported_faults = {
        "none",
        "localization_drift",
        "lidar_dropout",
        "cross_modal_disagreement",
        "obstacle_intrusion",
        "communication_loss",
        "compound_failure",
    }
    for item in raw.get("scenarios", []):
        scenario_id = str(item["id"])
        if scenario_id in seen_ids:
            raise ValueError(f"Duplicate scenario id: {scenario_id}")
        seen_ids.add(scenario_id)
        fault = str(item["fault"])
        if fault not in supported_faults:
            raise ValueError(f"Unsupported fault: {fault}")
        onset_s = (
            finite_float(item["onset_s"], f"{scenario_id}.onset_s")
            if item.get("onset_s") is not None
            else None
        )
        if fault == "none" and onset_s is not None:
            raise ValueError("Baseline scenario cannot define an onset")
        if fault != "none" and (onset_s is None or not 0 < onset_s < duration_s):
            raise ValueError(f"Fault scenario {scenario_id} requires an in-range onset")

        expected_monitor_ids = tuple(str(value) for value in item.get("expected_monitor_ids", []))
        if len(expected_monitor_ids) != len(set(expected_monitor_ids)):
            raise ValueError(f"Scenario {scenario_id} repeats an expected monitor")
        unknown_monitors = set(expected_monitor_ids) - set(policy.monitors_by_id)
        if unknown_monitors:
            raise ValueError(
                f"Scenario {scenario_id} references unknown monitors {sorted(unknown_monitors)}"
            )
        action_trigger_monitor_id = (
            str(item["action_trigger_monitor_id"])
            if item.get("action_trigger_monitor_id") is not None
            else None
        )
        if fault == "none":
            if expected_monitor_ids or action_trigger_monitor_id is not None:
                raise ValueError("Baseline cannot define expected or trigger monitors")
        elif (
            not expected_monitor_ids
            or action_trigger_monitor_id is None
            or action_trigger_monitor_id not in expected_monitor_ids
        ):
            raise ValueError(
                f"Fault scenario {scenario_id} requires expected monitors and a trigger among them"
            )
        expected_action = str(item["expected_action"])
        if expected_action not in policy.action_priority:
            raise ValueError(f"Scenario {scenario_id} references unknown action {expected_action}")
        if fault == "none" and expected_action != "CONTINUE":
            raise ValueError("Baseline expected action must be CONTINUE")
        scenarios.append(
            ScenarioDefinition(
                id=scenario_id,
                fault=fault,
                onset_s=onset_s,
                expected_monitor_ids=expected_monitor_ids,
                action_trigger_monitor_id=action_trigger_monitor_id,
                expected_action=expected_action,
            )
        )
    if not scenarios or scenarios[0].fault != "none":
        raise ValueError("Benchmark must begin with a baseline scenario")

    return BenchmarkDefinition(
        schema_version=str(raw["schema_version"]),
        duration_s=duration_s,
        sample_period_s=sample_period_s,
        scenario_oracle=scenario_oracle,
        representative_seed=representative_seed,
        seeds=seeds,
        scenarios=tuple(scenarios),
    )


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, value))


def _fault_progress(timestamp_s: float, onset_s: float, transition_s: float) -> float:
    return _clamp((timestamp_s - onset_s) / transition_s, 0.0, 1.0)


def _apply_fault(
    frame: dict[str, Any], scenario: ScenarioDefinition, timestamp_s: float, rng: random.Random
) -> None:
    if scenario.fault == "none" or scenario.onset_s is None or timestamp_s < scenario.onset_s:
        return
    elapsed = timestamp_s - scenario.onset_s
    frame["fault_active"] = True

    if scenario.fault == "localization_drift":
        progress = _fault_progress(timestamp_s, scenario.onset_s, 1.5)
        frame["localization_confidence"] = (
            (1.0 - progress) * float(frame["localization_confidence"])
            + progress * (0.34 + rng.gauss(0.0, 0.012))
        )
    elif scenario.fault == "lidar_dropout":
        frame["lidar_age_ms"] = 55.0 + 720.0 * elapsed + rng.uniform(-8.0, 8.0)
    elif scenario.fault == "cross_modal_disagreement":
        progress = _fault_progress(timestamp_s, scenario.onset_s, 1.2)
        frame["cross_modal_consistency"] = (
            (1.0 - progress) * float(frame["cross_modal_consistency"])
            + progress * (0.27 + rng.gauss(0.0, 0.015))
        )
    elif scenario.fault == "obstacle_intrusion":
        progress = _fault_progress(timestamp_s, scenario.onset_s, 1.8)
        frame["obstacle_distance_m"] = (
            (1.0 - progress) * float(frame["obstacle_distance_m"])
            + progress * (2.15 + rng.gauss(0.0, 0.025))
        )
    elif scenario.fault == "communication_loss":
        frame["comm_age_ms"] = 80.0 + 880.0 * elapsed + rng.uniform(-12.0, 12.0)
    elif scenario.fault == "compound_failure":
        progress = _fault_progress(timestamp_s, scenario.onset_s, 0.8)
        frame["localization_confidence"] = (1.0 - progress) * float(
            frame["localization_confidence"]
        ) + progress * 0.32
        frame["lidar_age_ms"] = 60.0 + 950.0 * elapsed
        frame["comm_age_ms"] = 80.0 + 1050.0 * elapsed
        if elapsed >= 0.6:
            frame["fallback_available"] = False


def generate_trace(
    scenario: ScenarioDefinition,
    seed: int,
    benchmark: BenchmarkDefinition,
    policy: AssurancePolicy,
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    sample_count = int(round(benchmark.duration_s / benchmark.sample_period_s))
    rows: list[dict[str, Any]] = []
    for index in range(sample_count):
        timestamp_s = round(index * benchmark.sample_period_s, 6)
        frame: dict[str, Any] = {
            "scenario_id": scenario.id,
            "fault": scenario.fault,
            "run_id": f"{scenario.id}-s{seed}",
            "seed": seed,
            "timestamp_s": timestamp_s,
            "localization_confidence": _clamp(0.94 + rng.gauss(0.0, 0.012), 0.0, 1.0),
            "lidar_age_ms": max(0.0, 48.0 + rng.gauss(0.0, 7.0)),
            "cross_modal_consistency": _clamp(0.92 + rng.gauss(0.0, 0.018), 0.0, 1.0),
            "obstacle_distance_m": 12.0
            + 0.35 * math.sin(timestamp_s / 4.0)
            + rng.gauss(0.0, 0.04),
            "speed_mps": max(
                0.0, 2.1 + 0.08 * math.sin(timestamp_s / 3.0) + rng.gauss(0.0, 0.025)
            ),
            "comm_age_ms": max(0.0, 78.0 + rng.gauss(0.0, 14.0)),
            "fallback_available": True,
            "fault_active": False,
            "scenario_oracle_positive": False,
        }
        _apply_fault(frame, scenario, timestamp_s, rng)

        oracle = benchmark.scenario_oracle
        stopping_margin = derive_metric(frame, policy.monitors_by_id["M-OBS-MARGIN"], policy)
        oracle_by_fault = {
            "none": False,
            "localization_drift": float(frame["localization_confidence"])
            <= oracle["localization_confidence_max"],
            "lidar_dropout": float(frame["lidar_age_ms"]) >= oracle["lidar_age_ms_min"],
            "cross_modal_disagreement": float(frame["cross_modal_consistency"])
            <= oracle["cross_modal_consistency_max"],
            "obstacle_intrusion": isinstance(stopping_margin, float)
            and stopping_margin <= oracle["stopping_margin_m_max"],
            "communication_loss": float(frame["comm_age_ms"]) >= oracle["comm_age_ms_min"],
            "compound_failure": (
                not bool(frame["fallback_available"])
                or float(frame["localization_confidence"])
                <= oracle["localization_confidence_max"]
                or float(frame["lidar_age_ms"]) >= oracle["lidar_age_ms_min"]
                or float(frame["comm_age_ms"]) >= oracle["comm_age_ms_min"]
            ),
        }
        frame["scenario_oracle_positive"] = bool(oracle_by_fault[scenario.fault])
        rows.append(frame)
    return rows


def _format_cell(column: str, value: Any) -> str | int:
    if isinstance(value, bool):
        return "true" if value else "false"
    if column == "seed":
        return int(value)
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def write_trace(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("Cannot write an empty trace")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=TRACE_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _format_cell(column, row[column]) for column in TRACE_COLUMNS})


def read_trace(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != TRACE_COLUMNS:
            raise ValueError(f"Unexpected trace schema in {path}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"Trace is empty: {path}")
    previous = -math.inf
    run_ids = {row["run_id"] for row in rows}
    if len(run_ids) != 1:
        raise ValueError(f"Trace contains multiple run ids: {path}")
    for row in rows:
        timestamp = finite_float(row["timestamp_s"], f"timestamp in {path}")
        if timestamp <= previous:
            raise ValueError(f"Trace timestamps must be finite and strictly increasing: {path}")
        previous = timestamp
    return rows
