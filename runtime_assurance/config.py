from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .models import AssurancePolicy, MonitorPolicy


def read_json(path: Path) -> dict[str, Any]:
    def reject_non_finite(token: str) -> None:
        raise ValueError(f"Non-finite JSON number {token!r} in {path}")

    value = json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=reject_non_finite,
    )
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _strict_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be an integer")
    numeric = finite_float(value, label)
    result = int(numeric)
    if numeric != result:
        raise ValueError(f"{label} must be an integer")
    return result


def _positive_int(value: Any, label: str) -> int:
    result = _strict_int(value, label)
    if result <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return result


def finite_float(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def load_policy(path: Path) -> AssurancePolicy:
    raw = read_json(path)
    persistence = raw.get("persistence", {})
    action_priority = {
        str(key): _positive_int(value, f"action_priority.{key}")
        for key, value in raw.get("action_priority", {}).items()
    }
    if "CONTINUE" not in action_priority:
        raise ValueError("Action priorities must define CONTINUE")
    if len(action_priority) != len(set(action_priority.values())):
        raise ValueError("Action priorities must be unique")
    if action_priority["CONTINUE"] != min(action_priority.values()):
        raise ValueError("CONTINUE must have the lowest action priority")

    flight_envelope = {
        str(key): finite_float(value, f"flight_envelope.{key}")
        for key, value in raw.get("flight_envelope", {}).items()
    }
    required_envelope = {
        "guaranteed_deceleration_lower_bound_mps2",
        "minimum_clearance_m",
        "response_time_budget_s",
    }
    if set(flight_envelope) != required_envelope:
        raise ValueError(f"flight_envelope must contain exactly {sorted(required_envelope)}")
    if flight_envelope["guaranteed_deceleration_lower_bound_mps2"] <= 0:
        raise ValueError("guaranteed_deceleration_lower_bound_mps2 must be positive")
    if (
        flight_envelope["minimum_clearance_m"] < 0
        or flight_envelope["response_time_budget_s"] < 0
    ):
        raise ValueError("Clearance and reaction time cannot be negative")

    monitors: list[MonitorPolicy] = []
    seen_ids: set[str] = set()
    for item in raw.get("monitors", []):
        monitor_id = str(item["id"])
        if monitor_id in seen_ids:
            raise ValueError(f"Duplicate monitor id: {monitor_id}")
        seen_ids.add(monitor_id)
        kind = str(item["kind"])
        if kind not in {"high_is_good", "low_is_good", "boolean_true"}:
            raise ValueError(f"Unsupported monitor kind for {monitor_id}: {kind}")
        pass_threshold = (
            finite_float(item["pass_threshold"], f"{monitor_id}.pass_threshold")
            if item.get("pass_threshold") is not None
            else None
        )
        fail_threshold = (
            finite_float(item["fail_threshold"], f"{monitor_id}.fail_threshold")
            if item.get("fail_threshold") is not None
            else None
        )
        if kind == "high_is_good":
            if pass_threshold is None or fail_threshold is None or fail_threshold >= pass_threshold:
                raise ValueError(f"Invalid high-is-good thresholds for {monitor_id}")
        elif kind == "low_is_good":
            if pass_threshold is None or fail_threshold is None or pass_threshold >= fail_threshold:
                raise ValueError(f"Invalid low-is-good thresholds for {monitor_id}")
        elif pass_threshold is not None or fail_threshold is not None:
            raise ValueError(f"Boolean monitor {monitor_id} must not define numeric thresholds")

        actions = [
            str(item["warning_action"]),
            str(item["failure_action"]),
            str(item["missing_action"]),
        ]
        unknown_actions = set(actions) - set(action_priority)
        if unknown_actions:
            raise ValueError(f"Unknown actions for {monitor_id}: {sorted(unknown_actions)}")
        action_levels = [action_priority[action] for action in actions]
        if action_levels != sorted(action_levels):
            raise ValueError(
                f"Actions for {monitor_id} must satisfy warning <= failure <= missing priority"
            )
        monitors.append(
            MonitorPolicy(
                id=monitor_id,
                metric=str(item["metric"]),
                kind=kind,
                pass_threshold=pass_threshold,
                fail_threshold=fail_threshold,
                warning_action=actions[0],
                failure_action=actions[1],
                missing_action=actions[2],
                unit=str(item["unit"]),
            )
        )
    if not monitors:
        raise ValueError("At least one monitor is required")

    return AssurancePolicy(
        schema_version=str(raw["schema_version"]),
        warning_samples=_positive_int(persistence.get("warning_samples"), "warning_samples"),
        failure_samples=_positive_int(persistence.get("failure_samples"), "failure_samples"),
        recovery_samples=_positive_int(persistence.get("recovery_samples"), "recovery_samples"),
        action_priority=action_priority,
        flight_envelope=flight_envelope,
        monitors=tuple(monitors),
    )
