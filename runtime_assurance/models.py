from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class EvidenceStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


STATUS_SEVERITY = {
    EvidenceStatus.PASS: 0,
    EvidenceStatus.WARN: 1,
    EvidenceStatus.FAIL: 2,
}


class ClaimSupportState(str, Enum):
    SUPPORTED = "SUPPORTED"
    DEGRADED = "DEGRADED"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class MonitorPolicy:
    id: str
    metric: str
    kind: str
    pass_threshold: float | None
    fail_threshold: float | None
    warning_action: str
    failure_action: str
    missing_action: str
    unit: str


@dataclass(frozen=True)
class AssurancePolicy:
    schema_version: str
    warning_samples: int
    failure_samples: int
    recovery_samples: int
    action_priority: dict[str, int]
    flight_envelope: dict[str, float]
    monitors: tuple[MonitorPolicy, ...]

    @property
    def monitors_by_id(self) -> dict[str, MonitorPolicy]:
        return {monitor.id: monitor for monitor in self.monitors}


@dataclass(frozen=True)
class MonitorObservation:
    monitor_id: str
    metric: str
    value: float | bool | None
    unit: str
    raw_status: EvidenceStatus
    status: EvidenceStatus
    action: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["raw_status"] = self.raw_status.value
        value["status"] = self.status.value
        return value


@dataclass(frozen=True)
class CaseSnapshot:
    timestamp_s: float
    argument_support_state: ClaimSupportState
    action: str
    top_claim_support: EvidenceStatus
    claim_support: dict[str, EvidenceStatus]
    observations: dict[str, MonitorObservation]
    affected_constraint_ids: tuple[str, ...]
    affected_hazard_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp_s": round(self.timestamp_s, 6),
            "argument_support_state": self.argument_support_state.value,
            "action": self.action,
            "top_claim_support": self.top_claim_support.value,
            "claim_support": {
                claim_id: status.value for claim_id, status in sorted(self.claim_support.items())
            },
            "affected_constraint_ids": list(self.affected_constraint_ids),
            "affected_hazard_ids": list(self.affected_hazard_ids),
            "observations": {
                monitor_id: observation.to_dict()
                for monitor_id, observation in sorted(self.observations.items())
            },
        }


def worst_status(statuses: list[EvidenceStatus] | tuple[EvidenceStatus, ...]) -> EvidenceStatus:
    if not statuses:
        return EvidenceStatus.FAIL
    return max(statuses, key=lambda status: STATUS_SEVERITY[status])
