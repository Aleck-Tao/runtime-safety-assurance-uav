from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from .models import AssurancePolicy, CaseSnapshot, EvidenceStatus
from .supervisor import RuntimeAssuranceSupervisor


def _csv_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(f"Expected true/false value, received {value!r}")


@dataclass(frozen=True)
class RunMetrics:
    run_id: str
    scenario_id: str
    seed: int
    expected_monitor_ids: str
    action_trigger_monitor_id: str | None
    expected_action: str
    fault_injection_onset_s: float | None
    scenario_oracle_onset_s: float | None
    trigger_monitor_raw_failure_s: float | None
    unsupported_support_onset_s: float | None
    exact_action_selection_s: float | None
    assurance_response_time_s: float | None
    policy_response_time_s: float | None
    time_at_risk_before_expected_action_s: float | None
    scenario_oracle_positive_coverage: float | None
    oracle_first_1s_unsupported_coverage: float | None
    pre_injection_intervention_rate: float
    pre_oracle_intervention_rate: float | None
    early_intervention_lead_s: float | None
    pre_oracle_maximum_action: str | None
    stopping_margin_violation_frames: int
    expected_monitors_activated: bool | None
    activated_expected_monitor_ids: str
    unexpected_monitor_activation: bool
    unexpected_activated_monitor_ids: str
    exact_expected_action_selected: bool | None
    overreaction_observed: bool
    overreaction_frames: int
    post_selection_underreaction_observed: bool
    post_selection_underreaction_frames: int
    state_action_transitions: int
    maximum_action: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key, item in list(value.items()):
            if isinstance(item, float):
                value[key] = round(item, 6)
        return value


@dataclass(frozen=True)
class ReplayResult:
    metrics: RunMetrics
    snapshots: tuple[CaseSnapshot, ...]
    transition_rows: tuple[dict[str, Any], ...]


def replay_trace(
    rows: list[dict[str, Any]],
    policy: AssurancePolicy,
    assurance_case: dict[str, Any],
    stpa_model: dict[str, Any],
    expected_monitor_ids: tuple[str, ...],
    action_trigger_monitor_id: str | None,
    expected_action: str,
) -> ReplayResult:
    if not rows:
        raise ValueError("Cannot replay an empty trace")
    supervisor = RuntimeAssuranceSupervisor(policy, assurance_case, stpa_model)
    snapshots: list[CaseSnapshot] = []
    transition_rows: list[dict[str, Any]] = []
    previous_state_action: tuple[str, str] | None = None

    fault_injection_onset_s: float | None = None
    scenario_oracle_onset_s: float | None = None
    trigger_monitor_raw_failure_s: float | None = None
    unsupported_support_onset_s: float | None = None
    exact_action_selection_s: float | None = None
    first_post_injection_intervention_s: float | None = None
    activated_monitors: set[str] = set()
    unexpected_monitors: set[str] = set()
    oracle_frames = 0
    oracle_unsupported_frames = 0
    first_window_frames = 0
    first_window_unsupported_frames = 0
    pre_injection_frames = 0
    pre_injection_intervention_frames = 0
    pre_oracle_frames = 0
    pre_oracle_intervention_frames = 0
    pre_oracle_actions: list[str] = []
    margin_violation_frames = 0
    overreaction_frames = 0
    post_selection_underreaction_frames = 0

    expected_set = set(expected_monitor_ids)
    for row in rows:
        snapshot = supervisor.step(row)
        snapshots.append(snapshot)
        timestamp_s = snapshot.timestamp_s
        oracle_positive = _csv_bool(row["scenario_oracle_positive"])
        fault_active = _csv_bool(row["fault_active"])
        support_unsupported = snapshot.argument_support_state.value == "UNSUPPORTED"

        if fault_active and fault_injection_onset_s is None:
            fault_injection_onset_s = timestamp_s
        if fault_active and snapshot.action != "CONTINUE" and first_post_injection_intervention_s is None:
            first_post_injection_intervention_s = timestamp_s
        if fault_active and support_unsupported and unsupported_support_onset_s is None:
            unsupported_support_onset_s = timestamp_s

        if oracle_positive:
            oracle_frames += 1
            if scenario_oracle_onset_s is None:
                scenario_oracle_onset_s = timestamp_s
            if support_unsupported:
                oracle_unsupported_frames += 1
            if timestamp_s < scenario_oracle_onset_s + 1.0:
                first_window_frames += 1
                if support_unsupported:
                    first_window_unsupported_frames += 1
        elif fault_active and scenario_oracle_onset_s is None:
            pre_oracle_frames += 1
            pre_oracle_actions.append(snapshot.action)
            if snapshot.action != "CONTINUE":
                pre_oracle_intervention_frames += 1

        if not fault_active:
            pre_injection_frames += 1
            if snapshot.action != "CONTINUE":
                pre_injection_intervention_frames += 1

        margin = snapshot.observations["M-OBS-MARGIN"].value
        if isinstance(margin, float) and margin <= 0.0:
            margin_violation_frames += 1

        for monitor_id, observation in snapshot.observations.items():
            if observation.status is EvidenceStatus.FAIL:
                activated_monitors.add(monitor_id)
                if monitor_id not in expected_set:
                    unexpected_monitors.add(monitor_id)

        if action_trigger_monitor_id is not None:
            trigger = snapshot.observations[action_trigger_monitor_id]
            if trigger.raw_status is EvidenceStatus.FAIL and trigger_monitor_raw_failure_s is None:
                trigger_monitor_raw_failure_s = timestamp_s
            if trigger_monitor_raw_failure_s is not None:
                if (
                    snapshot.action == expected_action
                    and trigger.status is EvidenceStatus.FAIL
                    and trigger.action == expected_action
                    and exact_action_selection_s is None
                ):
                    exact_action_selection_s = timestamp_s
                if (
                    policy.action_priority[snapshot.action]
                    > policy.action_priority[expected_action]
                ):
                    overreaction_frames += 1
                if (
                    exact_action_selection_s is not None
                    and oracle_positive
                    and policy.action_priority[snapshot.action]
                    < policy.action_priority[expected_action]
                ):
                    post_selection_underreaction_frames += 1

        state_action = (snapshot.argument_support_state.value, snapshot.action)
        if state_action != previous_state_action:
            failed_monitors = sorted(
                monitor_id
                for monitor_id, observation in snapshot.observations.items()
                if observation.status is EvidenceStatus.FAIL
            )
            warning_monitors = sorted(
                monitor_id
                for monitor_id, observation in snapshot.observations.items()
                if observation.status is EvidenceStatus.WARN
            )
            transition_rows.append(
                {
                    "run_id": str(row["run_id"]),
                    "timestamp_s": round(timestamp_s, 6),
                    "argument_support_state": snapshot.argument_support_state.value,
                    "action": snapshot.action,
                    "top_claim_support": snapshot.top_claim_support.value,
                    "warning_monitors": ";".join(warning_monitors),
                    "failed_monitors": ";".join(failed_monitors),
                    "action_source_monitors": ";".join(
                        sorted(
                            monitor_id
                            for monitor_id, observation in snapshot.observations.items()
                            if observation.action == snapshot.action
                        )
                    ),
                    "affected_constraint_ids": ";".join(snapshot.affected_constraint_ids),
                    "affected_hazard_ids": ";".join(snapshot.affected_hazard_ids),
                }
            )
            previous_state_action = state_action

    maximum_action = max(
        (snapshot.action for snapshot in snapshots), key=lambda action: policy.action_priority[action]
    )
    assurance_response_time_s = (
        unsupported_support_onset_s - scenario_oracle_onset_s
        if unsupported_support_onset_s is not None and scenario_oracle_onset_s is not None
        else None
    )
    policy_response_time_s = (
        exact_action_selection_s - trigger_monitor_raw_failure_s
        if exact_action_selection_s is not None and trigger_monitor_raw_failure_s is not None
        else None
    )
    time_at_risk_s = (
        max(0.0, exact_action_selection_s - scenario_oracle_onset_s)
        if exact_action_selection_s is not None and scenario_oracle_onset_s is not None
        else None
    )
    early_intervention_lead_s = (
        scenario_oracle_onset_s - first_post_injection_intervention_s
        if scenario_oracle_onset_s is not None
        and first_post_injection_intervention_s is not None
        and first_post_injection_intervention_s < scenario_oracle_onset_s
        else None
    )
    activated_expected = sorted(activated_monitors & expected_set)
    metrics = RunMetrics(
        run_id=str(rows[0]["run_id"]),
        scenario_id=str(rows[0]["scenario_id"]),
        seed=int(rows[0]["seed"]),
        expected_monitor_ids=";".join(expected_monitor_ids),
        action_trigger_monitor_id=action_trigger_monitor_id,
        expected_action=expected_action,
        fault_injection_onset_s=fault_injection_onset_s,
        scenario_oracle_onset_s=scenario_oracle_onset_s,
        trigger_monitor_raw_failure_s=trigger_monitor_raw_failure_s,
        unsupported_support_onset_s=unsupported_support_onset_s,
        exact_action_selection_s=exact_action_selection_s,
        assurance_response_time_s=assurance_response_time_s,
        policy_response_time_s=policy_response_time_s,
        time_at_risk_before_expected_action_s=time_at_risk_s,
        scenario_oracle_positive_coverage=(
            oracle_unsupported_frames / oracle_frames if oracle_frames else None
        ),
        oracle_first_1s_unsupported_coverage=(
            first_window_unsupported_frames / first_window_frames
            if first_window_frames
            else None
        ),
        pre_injection_intervention_rate=(
            pre_injection_intervention_frames / pre_injection_frames
            if pre_injection_frames
            else 0.0
        ),
        pre_oracle_intervention_rate=(
            pre_oracle_intervention_frames / pre_oracle_frames if pre_oracle_frames else None
        ),
        early_intervention_lead_s=early_intervention_lead_s,
        pre_oracle_maximum_action=(
            max(pre_oracle_actions, key=lambda action: policy.action_priority[action])
            if pre_oracle_actions
            else None
        ),
        stopping_margin_violation_frames=margin_violation_frames,
        expected_monitors_activated=(
            expected_set.issubset(activated_monitors) if expected_set else None
        ),
        activated_expected_monitor_ids=";".join(activated_expected),
        unexpected_monitor_activation=bool(unexpected_monitors),
        unexpected_activated_monitor_ids=";".join(sorted(unexpected_monitors)),
        exact_expected_action_selected=(
            exact_action_selection_s is not None if action_trigger_monitor_id is not None else None
        ),
        overreaction_observed=overreaction_frames > 0,
        overreaction_frames=overreaction_frames,
        post_selection_underreaction_observed=post_selection_underreaction_frames > 0,
        post_selection_underreaction_frames=post_selection_underreaction_frames,
        state_action_transitions=max(0, len(transition_rows) - 1),
        maximum_action=maximum_action,
    )
    return ReplayResult(
        metrics=metrics,
        snapshots=tuple(snapshots),
        transition_rows=tuple(transition_rows),
    )


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _rate(values: list[bool]) -> float | None:
    return sum(1 for value in values if value) / len(values) if values else None


def summarize_runs(runs: list[RunMetrics]) -> list[dict[str, Any]]:
    grouped: dict[str, list[RunMetrics]] = {}
    for run in runs:
        grouped.setdefault(run.scenario_id, []).append(run)
    summaries: list[dict[str, Any]] = []
    for scenario_id, items in grouped.items():
        assurance_times = [
            item.assurance_response_time_s
            for item in items
            if item.assurance_response_time_s is not None
        ]
        policy_times = [
            item.policy_response_time_s
            for item in items
            if item.policy_response_time_s is not None
        ]
        summary = {
            "scenario_id": scenario_id,
            "runs": len(items),
            "expected_monitor_activation_rate": _rate(
                [
                    item.expected_monitors_activated
                    for item in items
                    if item.expected_monitors_activated is not None
                ]
            ),
            "support_loss_detection_rate": (
                _rate([item.unsupported_support_onset_s is not None for item in items])
                if any(item.scenario_oracle_onset_s is not None for item in items)
                else None
            ),
            "exact_expected_action_rate": _rate(
                [
                    item.exact_expected_action_selected
                    for item in items
                    if item.exact_expected_action_selected is not None
                ]
            ),
            "unexpected_monitor_activation_rate": _rate(
                [item.unexpected_monitor_activation for item in items]
            ),
            "overreaction_run_rate": _rate([item.overreaction_observed for item in items]),
            "post_selection_underreaction_run_rate": _rate(
                [item.post_selection_underreaction_observed for item in items]
            ),
            "mean_assurance_response_time_s": _mean(assurance_times),
            "p95_assurance_response_time_s": _percentile(assurance_times, 0.95),
            "mean_policy_response_time_s": _mean(policy_times),
            "p95_policy_response_time_s": _percentile(policy_times, 0.95),
            "mean_time_at_risk_before_expected_action_s": _mean(
                [
                    item.time_at_risk_before_expected_action_s
                    for item in items
                    if item.time_at_risk_before_expected_action_s is not None
                ]
            ),
            "mean_scenario_oracle_positive_coverage": _mean(
                [
                    item.scenario_oracle_positive_coverage
                    for item in items
                    if item.scenario_oracle_positive_coverage is not None
                ]
            ),
            "mean_oracle_first_1s_unsupported_coverage": _mean(
                [
                    item.oracle_first_1s_unsupported_coverage
                    for item in items
                    if item.oracle_first_1s_unsupported_coverage is not None
                ]
            ),
            "mean_pre_injection_intervention_rate": _mean(
                [item.pre_injection_intervention_rate for item in items]
            ),
            "mean_pre_oracle_intervention_rate": _mean(
                [
                    item.pre_oracle_intervention_rate
                    for item in items
                    if item.pre_oracle_intervention_rate is not None
                ]
            ),
            "mean_early_intervention_lead_s": _mean(
                [
                    item.early_intervention_lead_s
                    for item in items
                    if item.early_intervention_lead_s is not None
                ]
            ),
            "mean_stopping_margin_violation_frames": _mean(
                [float(item.stopping_margin_violation_frames) for item in items]
            ),
            "mean_overreaction_frames": _mean(
                [float(item.overreaction_frames) for item in items]
            ),
            "mean_post_selection_underreaction_frames": _mean(
                [float(item.post_selection_underreaction_frames) for item in items]
            ),
            "pre_oracle_maximum_actions": sorted(
                {
                    item.pre_oracle_maximum_action
                    for item in items
                    if item.pre_oracle_maximum_action is not None
                }
            ),
            "maximum_actions": sorted({item.maximum_action for item in items}),
        }
        for key, value in list(summary.items()):
            if isinstance(value, float):
                summary[key] = round(value, 6)
        summaries.append(summary)
    return summaries
