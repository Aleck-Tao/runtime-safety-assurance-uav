from __future__ import annotations

from typing import Any

from .models import AssurancePolicy, EvidenceStatus, MonitorObservation, worst_status


def _unique_ids(items: list[dict[str, Any]], label: str) -> set[str]:
    identifiers = [str(item.get("id", "")) for item in items]
    if any(not identifier for identifier in identifiers):
        raise ValueError(f"Every {label} requires a non-empty id")
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(f"Duplicate {label} id")
    return set(identifiers)


def _require_text(value: Any, label: str) -> str:
    result = str(value).strip()
    if not result:
        raise ValueError(f"{label} requires non-empty text")
    return result


def validate_stpa_model(model: dict[str, Any]) -> None:
    _require_text(model.get("method_scope", ""), "method_scope")
    _require_text(model.get("analysis_system_boundary", ""), "analysis_system_boundary")
    _require_text(
        model.get("implemented_component_boundary", ""), "implemented_component_boundary"
    )

    loss_ids = _unique_ids(model.get("losses", []), "loss")
    hazard_ids = _unique_ids(model.get("hazards", []), "hazard")
    uca_ids = _unique_ids(model.get("unsafe_control_actions", []), "unsafe control action")
    constraint_ids = _unique_ids(model.get("safety_constraints", []), "safety constraint")
    scenario_ids = _unique_ids(model.get("causal_scenarios", []), "causal scenario")
    if not all((loss_ids, hazard_ids, uca_ids, constraint_ids, scenario_ids)):
        raise ValueError("STPA-informed model sections cannot be empty")

    control_structure = model.get("control_structure", {})
    components = control_structure.get("components", [])
    edges = control_structure.get("edges", [])
    component_ids = _unique_ids(components, "control-structure component")
    _unique_ids(edges, "control-structure edge")
    control_actions = {str(value) for value in control_structure.get("control_actions", [])}
    if not component_ids or not edges or not control_actions:
        raise ValueError("Control structure requires components, edges, and control actions")
    for edge in edges:
        endpoints = {str(edge.get("from_component_id", "")), str(edge.get("to_component_id", ""))}
        missing = endpoints - component_ids
        if missing:
            raise ValueError(f"Control edge {edge['id']} references unknown components: {sorted(missing)}")
        if str(edge.get("kind", "")) not in {"control_action", "feedback", "disturbance"}:
            raise ValueError(f"Control edge {edge['id']} has unsupported kind")
        if not edge.get("items"):
            raise ValueError(f"Control edge {edge['id']} requires at least one item")

    for hazard in model["hazards"]:
        references = set(hazard.get("loss_ids", []))
        if not references:
            raise ValueError(f"Hazard {hazard['id']} requires loss references")
        missing = references - loss_ids
        if missing:
            raise ValueError(f"Hazard {hazard['id']} references unknown losses: {sorted(missing)}")

    uca_by_id = {str(item["id"]): item for item in model["unsafe_control_actions"]}
    for uca in model["unsafe_control_actions"]:
        references = set(uca.get("hazard_ids", []))
        if not references:
            raise ValueError(f"UCA {uca['id']} requires hazard references")
        missing = references - hazard_ids
        if missing:
            raise ValueError(f"UCA {uca['id']} references unknown hazards: {sorted(missing)}")
        if str(uca.get("control_action", "")) not in control_actions:
            raise ValueError(f"UCA {uca['id']} references an undeclared control action")

    covered_ucas: set[str] = set()
    covered_hazards: set[str] = set()
    for constraint in model["safety_constraints"]:
        constraint_hazards = set(constraint.get("hazard_ids", []))
        constraint_ucas = set(constraint.get("uca_ids", []))
        if not constraint_hazards or not constraint_ucas:
            raise ValueError(f"Constraint {constraint['id']} requires hazard and UCA references")
        missing_hazards = constraint_hazards - hazard_ids
        if missing_hazards:
            raise ValueError(
                f"Constraint {constraint['id']} references unknown hazards: {sorted(missing_hazards)}"
            )
        missing_ucas = constraint_ucas - uca_ids
        if missing_ucas:
            raise ValueError(
                f"Constraint {constraint['id']} references unknown UCAs: {sorted(missing_ucas)}"
            )
        for uca_id in constraint_ucas:
            uca_hazards = set(uca_by_id[uca_id].get("hazard_ids", []))
            if not constraint_hazards.intersection(uca_hazards):
                raise ValueError(
                    f"Constraint {constraint['id']} has no hazard in common with UCA {uca_id}"
                )
        covered_ucas.update(constraint_ucas)
        covered_hazards.update(constraint_hazards)
    if covered_ucas != uca_ids:
        raise ValueError(f"UCAs without safety constraints: {sorted(uca_ids - covered_ucas)}")
    if covered_hazards != hazard_ids:
        raise ValueError(f"Hazards without safety constraints: {sorted(hazard_ids - covered_hazards)}")

    referenced_scenario_ucas: set[str] = set()
    for scenario in model["causal_scenarios"]:
        references = set(scenario.get("uca_ids", []))
        if not references:
            raise ValueError(f"Scenario {scenario['id']} requires UCA references")
        missing = references - uca_ids
        if missing:
            raise ValueError(f"Scenario {scenario['id']} references unknown UCAs: {sorted(missing)}")
        referenced_scenario_ucas.update(references)
    if referenced_scenario_ucas != uca_ids:
        raise ValueError(f"UCAs without causal scenarios: {sorted(uca_ids - referenced_scenario_ucas)}")


def validate_assurance_case(
    case: dict[str, Any], stpa_model: dict[str, Any], policy: AssurancePolicy
) -> None:
    validate_stpa_model(stpa_model)
    claims = case.get("claims", [])
    evidence = case.get("evidence", [])
    assumptions = case.get("assumptions", [])
    non_goals = case.get("non_goals", [])
    claim_ids = _unique_ids(claims, "claim")
    evidence_ids = _unique_ids(evidence, "evidence")
    assumption_ids = _unique_ids(assumptions, "assumption")
    _unique_ids(non_goals, "non-goal")
    if not assumption_ids or not non_goals:
        raise ValueError("Assurance case requires explicit assumptions and non-goals")
    for assumption in assumptions:
        _require_text(assumption.get("statement", ""), f"Assumption {assumption['id']}")
        if str(assumption.get("validation_status", "")) not in {"UNVALIDATED", "VALIDATED"}:
            raise ValueError(f"Assumption {assumption['id']} requires a validation status")
    for non_goal in non_goals:
        _require_text(non_goal.get("statement", ""), f"Non-goal {non_goal['id']}")

    constraint_ids = {str(item["id"]) for item in stpa_model["safety_constraints"]}
    monitor_ids = set(policy.monitors_by_id)
    top_claim_id = str(case.get("top_claim_id", ""))
    if top_claim_id not in claim_ids:
        raise ValueError(f"Unknown top claim: {top_claim_id}")

    evidence_by_id = {str(item["id"]): item for item in evidence}
    evidence_monitor_ids: set[str] = set()
    for item in evidence:
        monitor_id = str(item.get("monitor_id", ""))
        if monitor_id not in monitor_ids:
            raise ValueError(f"Evidence {item['id']} references unknown monitor: {monitor_id}")
        if monitor_id in evidence_monitor_ids:
            raise ValueError(f"Monitor {monitor_id} is mapped by more than one evidence item")
        evidence_monitor_ids.add(monitor_id)
    if evidence_monitor_ids != monitor_ids:
        missing = monitor_ids - evidence_monitor_ids
        raise ValueError(f"Policy monitors without evidence mappings: {sorted(missing)}")

    claims_by_id = {str(item["id"]): item for item in claims}
    used_evidence: set[str] = set()
    used_assumptions: set[str] = set()
    leaf_constraint_ids: set[str] = set()
    for claim in claims:
        claim_id = str(claim["id"])
        if claim.get("strategy") != "all":
            raise ValueError(f"Claim {claim_id} must use the supported 'all' strategy")
        child_ids = set(claim.get("child_claim_ids", []))
        claim_evidence_ids = set(claim.get("evidence_ids", []))
        if not child_ids and not claim_evidence_ids:
            raise ValueError(f"Claim {claim_id} has no support")
        unknown_children = child_ids - claim_ids
        if unknown_children:
            raise ValueError(f"Claim {claim_id} has unknown children: {sorted(unknown_children)}")
        unknown_evidence = claim_evidence_ids - evidence_ids
        if unknown_evidence:
            raise ValueError(f"Claim {claim_id} has unknown evidence: {sorted(unknown_evidence)}")
        used_evidence.update(claim_evidence_ids)

        claim_constraints = set(claim.get("constraint_ids", []))
        unknown_constraints = claim_constraints - constraint_ids
        if unknown_constraints:
            raise ValueError(
                f"Claim {claim_id} references unknown constraints: {sorted(unknown_constraints)}"
            )
        claim_assumptions = set(claim.get("assumption_ids", []))
        unknown_assumptions = claim_assumptions - assumption_ids
        if unknown_assumptions:
            raise ValueError(
                f"Claim {claim_id} references unknown assumptions: {sorted(unknown_assumptions)}"
            )
        used_assumptions.update(claim_assumptions)
        if not child_ids:
            if not claim_constraints:
                raise ValueError(f"Leaf claim {claim_id} requires a safety constraint")
            if not claim_assumptions:
                raise ValueError(f"Leaf claim {claim_id} requires an explicit assumption")
            leaf_constraint_ids.update(claim_constraints)

    if used_evidence != evidence_ids:
        raise ValueError(f"Unused evidence items: {sorted(evidence_ids - used_evidence)}")
    if used_assumptions != assumption_ids:
        raise ValueError(f"Unused assumptions: {sorted(assumption_ids - used_assumptions)}")
    if leaf_constraint_ids != constraint_ids:
        raise ValueError(
            f"Safety constraints without leaf-claim coverage: {sorted(constraint_ids - leaf_constraint_ids)}"
        )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(claim_id: str) -> None:
        if claim_id in visiting:
            raise ValueError(f"Cycle detected at claim {claim_id}")
        if claim_id in visited:
            return
        visiting.add(claim_id)
        for child_id in claims_by_id[claim_id].get("child_claim_ids", []):
            visit(str(child_id))
        visiting.remove(claim_id)
        visited.add(claim_id)

    visit(top_claim_id)
    if visited != claim_ids:
        raise ValueError(f"Claims unreachable from top claim: {sorted(claim_ids - visited)}")

    for evidence_id, item in evidence_by_id.items():
        if not str(item.get("artifact", "")).strip():
            raise ValueError(f"Evidence {evidence_id} requires an artifact description")


def evaluate_claims(
    case: dict[str, Any], observations: dict[str, MonitorObservation]
) -> dict[str, EvidenceStatus]:
    claims_by_id = {str(item["id"]): item for item in case["claims"]}
    evidence_by_id = {str(item["id"]): item for item in case["evidence"]}
    result: dict[str, EvidenceStatus] = {}

    def evaluate(claim_id: str) -> EvidenceStatus:
        if claim_id in result:
            return result[claim_id]
        claim = claims_by_id[claim_id]
        supports: list[EvidenceStatus] = []
        for child_id in claim.get("child_claim_ids", []):
            supports.append(evaluate(str(child_id)))
        for evidence_id in claim.get("evidence_ids", []):
            monitor_id = str(evidence_by_id[str(evidence_id)]["monitor_id"])
            observation = observations.get(monitor_id)
            supports.append(observation.status if observation else EvidenceStatus.FAIL)
        result[claim_id] = worst_status(supports)
        return result[claim_id]

    evaluate(str(case["top_claim_id"]))
    return result
