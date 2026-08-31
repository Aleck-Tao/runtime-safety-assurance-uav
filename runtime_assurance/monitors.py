from __future__ import annotations

import math
from typing import Any

from .models import AssurancePolicy, EvidenceStatus, MonitorObservation, MonitorPolicy, STATUS_SEVERITY


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _strict_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1"}:
            return True
        if normalized in {"false", "0"}:
            return False
    return None


def derive_metric(
    frame: dict[str, Any], monitor: MonitorPolicy, policy: AssurancePolicy
) -> float | bool | None:
    if monitor.metric != "stopping_margin_m":
        if monitor.kind == "boolean_true":
            return _strict_bool(frame.get(monitor.metric))
        return _finite_number(frame.get(monitor.metric))

    obstacle_distance = _finite_number(frame.get("obstacle_distance_m"))
    speed = _finite_number(frame.get("speed_mps"))
    if obstacle_distance is None or speed is None or speed < 0:
        return None
    envelope = policy.flight_envelope
    braking_distance = speed * speed / (
        2.0 * envelope["guaranteed_deceleration_lower_bound_mps2"]
    )
    reaction_distance = speed * envelope["response_time_budget_s"]
    margin = (
        obstacle_distance
        - envelope["minimum_clearance_m"]
        - reaction_distance
        - braking_distance
    )
    return margin if math.isfinite(margin) else None


def evaluate_raw(
    monitor: MonitorPolicy, value: float | bool | None
) -> tuple[EvidenceStatus, str, str]:
    if value is None:
        return EvidenceStatus.FAIL, "missing or non-finite input", monitor.missing_action

    if monitor.kind == "boolean_true":
        if value is True:
            return EvidenceStatus.PASS, "required capability is available", "CONTINUE"
        return EvidenceStatus.FAIL, "required capability is unavailable", monitor.failure_action

    numeric = float(value)
    assert monitor.pass_threshold is not None
    assert monitor.fail_threshold is not None
    if monitor.kind == "high_is_good":
        if numeric >= monitor.pass_threshold:
            return EvidenceStatus.PASS, f"value >= {monitor.pass_threshold:g}", "CONTINUE"
        if numeric <= monitor.fail_threshold:
            return EvidenceStatus.FAIL, f"value <= {monitor.fail_threshold:g}", monitor.failure_action
        return EvidenceStatus.WARN, "value is inside warning band", monitor.warning_action

    if numeric <= monitor.pass_threshold:
        return EvidenceStatus.PASS, f"value <= {monitor.pass_threshold:g}", "CONTINUE"
    if numeric >= monitor.fail_threshold:
        return EvidenceStatus.FAIL, f"value >= {monitor.fail_threshold:g}", monitor.failure_action
    return EvidenceStatus.WARN, "value is inside warning band", monitor.warning_action


class PersistentMonitor:
    def __init__(self, monitor: MonitorPolicy, policy: AssurancePolicy) -> None:
        self.monitor = monitor
        self.policy = policy
        self.status = EvidenceStatus.PASS
        self.action = "CONTINUE"
        self._non_pass_count = 0
        self._fail_count = 0
        self._recovery_candidate: EvidenceStatus | None = None
        self._recovery_count = 0
        self._raw_action_candidate: str | None = None
        self._raw_action_count = 0
        self._action_recovery_candidate: str | None = None
        self._action_recovery_count = 0

    def _track_raw_action(self, action: str) -> None:
        if action == self._raw_action_candidate:
            self._raw_action_count += 1
        else:
            self._raw_action_candidate = action
            self._raw_action_count = 1

    def _reset_status_counters(self) -> None:
        self._non_pass_count = 0
        self._fail_count = 0
        self._recovery_candidate = None
        self._recovery_count = 0

    def _transition_status(self, raw_status: EvidenceStatus, raw_action: str) -> None:
        if self.status is EvidenceStatus.PASS:
            if raw_status is EvidenceStatus.PASS:
                self._reset_status_counters()
                return
            self._non_pass_count += 1
            self._fail_count = self._fail_count + 1 if raw_status is EvidenceStatus.FAIL else 0
            if self._fail_count >= self.policy.failure_samples:
                self.status = EvidenceStatus.FAIL
                self.action = (
                    raw_action
                    if self._raw_action_count >= self.policy.failure_samples
                    else self.monitor.failure_action
                )
                self._reset_status_counters()
            elif self._non_pass_count >= self.policy.warning_samples:
                self.status = EvidenceStatus.WARN
                self.action = self.monitor.warning_action
                self._non_pass_count = 0
                self._recovery_candidate = None
                self._recovery_count = 0
            return

        if self.status is EvidenceStatus.WARN:
            if raw_status is EvidenceStatus.FAIL:
                self._fail_count += 1
                self._recovery_candidate = None
                self._recovery_count = 0
                if self._fail_count >= self.policy.failure_samples:
                    self.status = EvidenceStatus.FAIL
                    self.action = (
                        raw_action
                        if self._raw_action_count >= self.policy.failure_samples
                        else self.monitor.failure_action
                    )
                    self._reset_status_counters()
                return
            self._fail_count = 0
            if raw_status is EvidenceStatus.WARN:
                self._recovery_candidate = None
                self._recovery_count = 0
                return
            candidate = EvidenceStatus.PASS
        else:
            if raw_status is EvidenceStatus.FAIL:
                self._recovery_candidate = None
                self._recovery_count = 0
                return
            self._recovery_count += 1
            if (
                self._recovery_candidate is None
                or STATUS_SEVERITY[raw_status] > STATUS_SEVERITY[self._recovery_candidate]
            ):
                self._recovery_candidate = raw_status
            if self._recovery_count >= self.policy.recovery_samples:
                candidate = self._recovery_candidate
                assert candidate is not None
                self.status = candidate
                self.action = (
                    "CONTINUE"
                    if candidate is EvidenceStatus.PASS
                    else self.monitor.warning_action
                )
                self._reset_status_counters()
            return

        if candidate == self._recovery_candidate:
            self._recovery_count += 1
        else:
            self._recovery_candidate = candidate
            self._recovery_count = 1
        if self._recovery_count >= self.policy.recovery_samples:
            self.status = candidate
            self.action = (
                "CONTINUE" if candidate is EvidenceStatus.PASS else self.monitor.warning_action
            )
            self._reset_status_counters()

    def _transition_action(self, raw_status: EvidenceStatus, raw_action: str) -> None:
        if raw_status is not self.status or self.status is EvidenceStatus.PASS:
            self._action_recovery_candidate = None
            self._action_recovery_count = 0
            return
        raw_priority = self.policy.action_priority[raw_action]
        current_priority = self.policy.action_priority[self.action]
        if raw_priority > current_priority:
            self._action_recovery_candidate = None
            self._action_recovery_count = 0
            if self._raw_action_count >= self.policy.failure_samples:
                self.action = raw_action
            return
        if raw_priority == current_priority:
            self._action_recovery_candidate = None
            self._action_recovery_count = 0
            return
        if raw_action == self._action_recovery_candidate:
            self._action_recovery_count += 1
        else:
            self._action_recovery_candidate = raw_action
            self._action_recovery_count = 1
        if self._action_recovery_count >= self.policy.recovery_samples:
            self.action = raw_action
            self._action_recovery_candidate = None
            self._action_recovery_count = 0

    def update(self, frame: dict[str, Any]) -> MonitorObservation:
        value = derive_metric(frame, self.monitor, self.policy)
        raw_status, reason, raw_action = evaluate_raw(self.monitor, value)
        effective_action = "CONTINUE" if raw_status is EvidenceStatus.PASS else raw_action
        self._track_raw_action(effective_action)
        previous_status = self.status
        self._transition_status(raw_status, effective_action)
        if self.status is previous_status:
            self._transition_action(raw_status, effective_action)

        return MonitorObservation(
            monitor_id=self.monitor.id,
            metric=self.monitor.metric,
            value=round(value, 6) if isinstance(value, float) else value,
            unit=self.monitor.unit,
            raw_status=raw_status,
            status=self.status,
            action=self.action,
            reason=reason,
        )
