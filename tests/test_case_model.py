from __future__ import annotations

import copy
import unittest
from pathlib import Path

from runtime_assurance.assurance_case import validate_assurance_case, validate_stpa_model
from runtime_assurance.config import load_policy, read_json


ROOT = Path(__file__).resolve().parents[1]


class CaseModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_policy(ROOT / "config" / "assurance_policy.json")
        self.case = read_json(ROOT / "assurance_case" / "uav_runtime_case.json")
        self.stpa = read_json(ROOT / "hazards" / "stpa_model.json")

    def test_committed_models_are_referentially_complete(self) -> None:
        validate_assurance_case(self.case, self.stpa, self.policy)

    def test_unmapped_monitor_is_rejected(self) -> None:
        invalid = copy.deepcopy(self.case)
        invalid["evidence"] = invalid["evidence"][:-1]
        with self.assertRaisesRegex(ValueError, "without evidence mappings"):
            validate_assurance_case(invalid, self.stpa, self.policy)

    def test_claim_cycle_is_rejected(self) -> None:
        invalid = copy.deepcopy(self.case)
        invalid["claims"].extend(
            [
                {"id": "C-LOOP-A", "strategy": "all", "child_claim_ids": ["C-LOOP-B"]},
                {"id": "C-LOOP-B", "strategy": "all", "child_claim_ids": ["C-LOOP-A"]},
            ]
        )
        invalid["claims"][0]["child_claim_ids"].append("C-LOOP-A")
        with self.assertRaisesRegex(ValueError, "Cycle detected"):
            validate_assurance_case(invalid, self.stpa, self.policy)

    def test_unknown_stpa_reference_is_rejected(self) -> None:
        invalid = copy.deepcopy(self.stpa)
        invalid["safety_constraints"][0]["hazard_ids"] = ["H-UNKNOWN"]
        with self.assertRaisesRegex(ValueError, "unknown hazards"):
            validate_stpa_model(invalid)

    def test_constraint_with_unknown_uca_is_rejected(self) -> None:
        invalid = copy.deepcopy(self.stpa)
        invalid["safety_constraints"][0]["uca_ids"] = ["UCA-UNKNOWN"]
        with self.assertRaisesRegex(ValueError, "unknown UCAs"):
            validate_stpa_model(invalid)

    def test_constraint_and_uca_must_share_a_hazard(self) -> None:
        invalid = copy.deepcopy(self.stpa)
        invalid["safety_constraints"][0]["hazard_ids"] = ["H-2"]
        with self.assertRaisesRegex(ValueError, "no hazard in common"):
            validate_stpa_model(invalid)

    def test_every_constraint_requires_leaf_claim_coverage(self) -> None:
        invalid = copy.deepcopy(self.case)
        for claim in invalid["claims"]:
            if claim["id"] == "C-SEPARATION":
                claim["constraint_ids"] = ["SC-2"]
        with self.assertRaisesRegex(ValueError, "without leaf-claim coverage"):
            validate_assurance_case(invalid, self.stpa, self.policy)

    def test_unused_assumption_is_rejected(self) -> None:
        invalid = copy.deepcopy(self.case)
        invalid["assumptions"].append(
            {
                "id": "A-UNUSED",
                "validation_status": "UNVALIDATED",
                "statement": "A deliberately unused assumption for validation testing.",
            }
        )
        with self.assertRaisesRegex(ValueError, "Unused assumptions"):
            validate_assurance_case(invalid, self.stpa, self.policy)


if __name__ == "__main__":
    unittest.main()
