from __future__ import annotations

import math
from typing import Any

from .assurance_case import evaluate_claims, validate_assurance_case
from .models import AssurancePolicy, CaseSnapshot, ClaimSupportState, EvidenceStatus
from .monitors import PersistentMonitor


SUPPORT_STATE_BY_STATUS = {
    EvidenceStatus.PASS: ClaimSupportState.SUPPORTED,
    EvidenceStatus.WARN: ClaimSupportState.DEGRADED,
    EvidenceStatus.FAIL: ClaimSupportState.UNSUPPORTED,
}


class RuntimeAssuranceSupervisor:
    def __init__(
        self,
        policy: AssurancePolicy,
        assurance_case: dict[str, Any],
        stpa_model: dict[str, Any],
    ) -> None:
        validate_assurance_case(assurance_case, stpa_model, policy)
        self.policy = policy
        self.assurance_case = assurance_case
        self.stpa_model = stpa_model
        self.monitors = {
            item.id: PersistentMonitor(item, policy) for item in policy.monitors
        }

    def _select_action(self, actions: list[str]) -> str:
        if not actions:
            return "ABORT"
        return max(actions, key=lambda action: self.policy.action_priority[action])

    def step(self, frame: dict[str, Any]) -> CaseSnapshot:
        try:
            timestamp_s = float(frame["timestamp_s"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Telemetry frame requires numeric timestamp_s") from exc
        if not math.isfinite(timestamp_s):
            raise ValueError("Telemetry timestamp_s must be finite")

        observations = {
            monitor_id: monitor.update(frame) for monitor_id, monitor in self.monitors.items()
        }
        claim_statuses = evaluate_claims(self.assurance_case, observations)
        top_claim_status = claim_statuses[str(self.assurance_case["top_claim_id"])]
        action = self._select_action(
            [observation.action for observation in observations.values()]
        )
        affected_constraint_ids = sorted(
            {
                str(constraint_id)
                for claim in self.assurance_case["claims"]
                if not claim.get("child_claim_ids")
                and claim_statuses[str(claim["id"])] is not EvidenceStatus.PASS
                for constraint_id in claim.get("constraint_ids", [])
            }
        )
        constraints_by_id = {
            str(item["id"]): item for item in self.stpa_model["safety_constraints"]
        }
        affected_hazard_ids = sorted(
            {
                str(hazard_id)
                for constraint_id in affected_constraint_ids
                for hazard_id in constraints_by_id[constraint_id].get("hazard_ids", [])
            }
        )
        return CaseSnapshot(
            timestamp_s=timestamp_s,
            argument_support_state=SUPPORT_STATE_BY_STATUS[top_claim_status],
            action=action,
            top_claim_support=top_claim_status,
            claim_support=claim_statuses,
            observations=observations,
            affected_constraint_ids=tuple(affected_constraint_ids),
            affected_hazard_ids=tuple(affected_hazard_ids),
        )
