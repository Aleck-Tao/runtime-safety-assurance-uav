"""Event-level threshold/persistence experiment using the existing supervisor."""
from __future__ import annotations

from dataclasses import replace
import math
from pathlib import Path
import random
from tempfile import TemporaryDirectory
from typing import Any

from .config import load_policy, read_json, write_json
from .models import AssurancePolicy
from .provenance import _expected_source_paths, _verify_entries
from .reporting import sha256_file, write_csv
from .supervisor import RuntimeAssuranceSupervisor


OUTPUTS = ("summary.json", "runs.csv", "events.csv", "telemetry.csv", "transitions.csv")
PATTERNS = ("short_pulses", "boundary_noise", "repeated_recovery", "slow_ramp")
INPUT_FIELDS = ["family", "pattern", "seed", "sample", "timestamp_s", "oracle_positive",
                "localization_confidence", "lidar_age_ms", "cross_modal_consistency",
                "obstacle_distance_m", "speed_mps", "comm_age_ms", "fallback_available"]


def load_settings(root: Path) -> dict[str, Any]:
    settings = read_json(root / "experiments/persistence_study.json")
    # This first study deliberately fixes the signal profiles and time grid.
    if settings.get("sample_period_s") != .1 or settings.get("assessment_samples") != 150:
        raise ValueError("this study requires a 150-sample assessment at 0.1 seconds")
    if settings.get("patterns") != list(PATTERNS):
        raise ValueError("study patterns must match the four declared profiles")
    if settings.get("failure_samples") != [1, 3, 5]:
        raise ValueError("failure_samples must be [1, 3, 5]")
    seeds = settings.get("seeds", [])
    if (not seeds or any(isinstance(x, bool) or not isinstance(x, int) or x < 0 for x in seeds)
            or len(seeds) != len(set(seeds))):
        raise ValueError("seeds must be unique non-negative integers")
    if set(settings.get("families", {})) != {"localization", "obstacle"}:
        raise ValueError("study requires localization and obstacle families")
    expected = {"localization": ("M-LOC", .45), "obstacle": ("M-OBS-MARGIN", 0.)}
    base = load_policy(root / "config/assurance_policy.json")
    for family, definition in settings["families"].items():
        if (definition.get("monitor_id"), definition.get("oracle_threshold")) != expected[family]:
            raise ValueError("oracle and monitor mapping are fixed independently of swept thresholds")
        thresholds = definition.get("failure_thresholds", [])
        if (not thresholds or any(isinstance(x, bool) or not isinstance(x, (int, float))
                or not math.isfinite(x) or x >= base.monitors_by_id[definition["monitor_id"]].pass_threshold
                for x in thresholds) or len(thresholds) != len(set(thresholds))):
            raise ValueError("failure thresholds must be unique, finite and below the pass threshold")
    return settings


def make_trace(family: str, pattern: str, seed: int, policy: AssurancePolicy,
               settings: dict[str, Any]) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    rows = []
    for index in range(settings["assessment_samples"]):
        severe = False
        if pattern == "short_pulses":
            severe = any(start <= index < start + length for start, length in
                         ((20, 1), (40, 2), (60, 3), (80, 5)))
        elif pattern == "repeated_recovery":
            severe = any(start <= index < start + 10 for start in (20, 36, 52))
        localization = .95 + rng.uniform(-.004, .004)
        margin = 3.0 + rng.uniform(-.03, .03)
        if family == "localization":
            if severe:
                localization = .30 + rng.uniform(-.005, .005)
            elif pattern == "boundary_noise" and 20 <= index < 100:
                localization = .57 + rng.uniform(-.04, .04)
            elif pattern == "slow_ramp" and 20 <= index < 60:
                localization = .90 - .60 * min(1., (index - 20) / 20)
            value = round(localization, 8)
        else:
            if severe:
                margin = -.60 + rng.uniform(-.01, .01)
            elif pattern == "boundary_noise" and 20 <= index < 100:
                margin = .15 + rng.uniform(-.10, .10)
            elif pattern == "slow_ramp" and 20 <= index < 60:
                margin = 2.0 - 2.6 * min(1., (index - 20) / 20)
            value = round(margin, 8)
        speed = 2.
        envelope = policy.flight_envelope
        distance = (margin + envelope["minimum_clearance_m"] + speed * envelope["response_time_budget_s"]
                    + speed * speed / (2 * envelope["guaranteed_deceleration_lower_bound_mps2"]))
        rows.append({"family": family, "pattern": pattern, "seed": seed, "sample": index,
            "timestamp_s": round(index * settings["sample_period_s"], 6),
            "oracle_positive": value <= settings["families"][family]["oracle_threshold"],
            "localization_confidence": round(localization, 8), "lidar_age_ms": 50.,
            "cross_modal_consistency": .92, "obstacle_distance_m": round(distance, 8),
            "speed_mps": speed, "comm_age_ms": 80., "fallback_available": True})
    return rows


def intervals(flags: list[bool]) -> list[tuple[int, int]]:
    result, start = [], None
    for index, active in enumerate([*flags, False]):
        if active and start is None:
            start = index
        elif not active and start is not None:
            result.append((start, index))
            start = None
    return result


def event_metrics(oracle: list[bool], selected: list[bool], period: float,
                  assessment_samples: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if len(oracle) != len(selected) or len(oracle) < assessment_samples:
        raise ValueError("aligned oracle and action samples must cover the assessment window")
    truth, actions = oracle[:assessment_samples], selected[:assessment_samples]
    events, episodes = intervals(truth), intervals(actions)
    records = []
    for event_index, (start, stop) in enumerate(events):
        overlaps = [(a, b) for a, b in episodes if a < stop and b > start]
        detected = bool(overlaps)
        onset_offset = (overlaps[0][0] - start) * period if overlaps else None
        next_start = events[event_index + 1][0] if event_index + 1 < len(events) else assessment_samples
        recovery_index = next((index for index in range(stop, next_start) if not actions[index]), None)
        recovery_delay = (recovery_index - stop) * period if detected and recovery_index is not None else None
        records.append({"event_index": event_index, "onset_s": round(start * period, 6),
            "end_s": round(stop * period, 6), "positive_samples": stop - start,
            "detected": detected,
            "detection_delay_s": round(max(0., onset_offset), 6) if detected else None,
            "signed_action_onset_offset_s": round(onset_offset, 6) if detected else None,
            "recovery_delay_s": round(recovery_delay, 6) if recovery_delay is not None else None,
            "recovery_censored": detected and recovery_index is None,
            "event_right_censored": stop == assessment_samples})
    detected_count = sum(item["detected"] for item in records)
    delays = [item["detection_delay_s"] for item in records if item["detected"]]
    unmatched = sum(not any(a < stop and b > start for start, stop in events) for a, b in episodes)
    return {"event_count": len(events), "detected_events": detected_count,
            "missed_events": len(events) - detected_count,
            "event_recall": detected_count / len(events) if events else None,
            "max_detected_delay_s": max(delays) if delays else None,
            "unmatched_action_episodes": unmatched,
            "oracle_negative_action_samples": sum(action and not positive for action, positive in zip(actions, truth)),
            "recovery_censored_events": sum(item["recovery_censored"] for item in records)}, records


def _source_names(root: Path) -> list[str]:
    return sorted(_expected_source_paths(root) | {"experiments/persistence_study.json",
        ".github/workflows/ci.yml", "tests/test_persistence_study.py"})


def _entries(root: Path, names: list[str] | tuple[str, ...]) -> list[dict[str, Any]]:
    return [{"path": name, "bytes": (root / name).stat().st_size,
             "sha256": sha256_file(root / name)} for name in names]


def run_study(root: Path, output: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    output = output or root / "studies/persistence"
    settings = load_settings(root)
    base = load_policy(root / "config/assurance_policy.json")
    case = read_json(root / "assurance_case/uav_runtime_case.json")
    stpa = read_json(root / "hazards/stpa_model.json")
    runs, events, inputs, transitions = [], [], [], []
    unique_events = 0
    for family, definition in sorted(settings["families"].items()):
        monitor_id = definition["monitor_id"]
        for pattern in settings["patterns"]:
            for seed in settings["seeds"]:
                rows = make_trace(family, pattern, seed, base, settings)
                inputs.extend(rows)
                unique_events += len(intervals([row["oracle_positive"] for row in rows]))
                for threshold in definition["failure_thresholds"]:
                    for persistence in settings["failure_samples"]:
                        policy = replace(base, failure_samples=persistence,
                            monitors=tuple(replace(m, fail_threshold=threshold) if m.id == monitor_id else m
                                           for m in base.monitors))
                        supervisor = RuntimeAssuranceSupervisor(policy, case, stpa)
                        run_id = f"{family}__{pattern}__{seed}__threshold_{threshold:g}__n{persistence}"
                        identity = {"run_id": run_id, "family": family, "pattern": pattern, "seed": seed,
                                    "failure_threshold": threshold, "failure_samples": persistence}
                        selected, previous = [], None
                        for row in rows:
                            snapshot = supervisor.step(row)
                            selected.append(policy.action_priority[snapshot.action] >= policy.action_priority["HOVER"])
                            observation = snapshot.observations[monitor_id]
                            key = (snapshot.action, observation.raw_status.value,
                                   observation.status.value, row["oracle_positive"])
                            if key != previous:
                                transitions.append({"run_id": run_id, "sample": row["sample"],
                                    "timestamp_s": row["timestamp_s"], "action": snapshot.action,
                                    "raw_status": observation.raw_status.value,
                                    "status": observation.status.value, "oracle_positive": row["oracle_positive"]})
                                previous = key
                        metrics, records = event_metrics([row["oracle_positive"] for row in rows],
                            selected, settings["sample_period_s"], settings["assessment_samples"])
                        runs.append({**identity, **metrics})
                        events.extend({"run_id": run_id, **event} for event in records)
    groups = []
    for family, definition in sorted(settings["families"].items()):
        for pattern in settings["patterns"]:
            for threshold in definition["failure_thresholds"]:
                for persistence in settings["failure_samples"]:
                    group = [run for run in runs if run["family"] == family and run["pattern"] == pattern
                             and run["failure_threshold"] == threshold and run["failure_samples"] == persistence]
                    total_events = sum(run["event_count"] for run in group)
                    detected = sum(run["detected_events"] for run in group)
                    delays = [run["max_detected_delay_s"] for run in group if run["max_detected_delay_s"] is not None]
                    groups.append({"family": family, "pattern": pattern, "failure_threshold": threshold,
                        "failure_samples": persistence, "runs": len(group), "events": total_events,
                        "detected_events": detected, "missed_events": total_events - detected,
                        "event_recall": detected / total_events if total_events else None,
                        "max_detected_delay_s": max(delays) if delays else None,
                        "unmatched_action_episodes": sum(run["unmatched_action_episodes"] for run in group),
                        "oracle_negative_action_samples": sum(run["oracle_negative_action_samples"] for run in group)})
    summary = {"schema_version": 1, "run_count": len(runs),
        "input_trace_count": len(inputs) // settings["assessment_samples"],
        "unique_oracle_events": unique_events, "event_policy_evaluations": len(events),
        "sample_period_s": settings["sample_period_s"],
        "assessment_samples": settings["assessment_samples"],
        "selected_action": "HOVER or higher priority; SLOW is not counted as event detection",
        "oracle": "Fixed signal criterion independent of swept monitor threshold",
        "unmatched_action_episode": "A contiguous HOVER-or-higher episode overlapping no positive oracle event",
        "groups": groups}
    write_json(output / "summary.json", summary)
    for name, rows in (("runs.csv", runs), ("events.csv", events), ("telemetry.csv", inputs),
                       ("transitions.csv", transitions)):
        write_csv(output / name, list(rows[0]) if name != "telemetry.csv" else INPUT_FIELDS, rows)
    write_json(output / "manifest.json", {"schema_version": 1,
        "generated_by": "runtime-assurance persistence-study",
        "sources": _entries(root, _source_names(root)), "results": _entries(output, OUTPUTS)})
    return {"run_count": len(runs), "event_policy_evaluations": len(events), "output": str(output)}


def verify_study(root: Path) -> dict[str, Any]:
    root = root.resolve()
    output = root / "studies/persistence"
    manifest = read_json(output / "manifest.json")
    sources = _verify_entries(root, manifest["sources"])
    results = _verify_entries(output, manifest["results"])
    if sources != set(_source_names(root)) or results != set(OUTPUTS):
        raise ValueError("persistence study manifest coverage mismatch")
    actual = {path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()}
    if actual != {*OUTPUTS, "manifest.json"}:
        raise ValueError("unexpected persistence study result file")
    return {"valid": True, "results_verified": len(OUTPUTS)}


def check_study(root: Path) -> dict[str, Any]:
    root = root.resolve()
    verify_study(root)
    with TemporaryDirectory(prefix="runtime-persistence-") as temporary:
        output = Path(temporary)
        run_study(root, output)
        for name in OUTPUTS:
            if (output / name).read_bytes() != (root / "studies/persistence" / name).read_bytes():
                raise ValueError(f"persistence study reproduction mismatch: {name}")
    return {"reproducible": True, "files_compared": len(OUTPUTS)}
