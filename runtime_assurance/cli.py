from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .assurance_case import validate_assurance_case
from .config import load_policy, read_json
from .pipeline import run_benchmark
from .provenance import verify_manifest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="runtime-assurance",
        description="Validate and execute a runtime-updated UAV assurance-case benchmark.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Lint policy, STPA model, and assurance case")
    validate.add_argument("--root", type=Path, default=PROJECT_ROOT)

    verify = subparsers.add_parser(
        "verify", help="Verify committed source, trace, and result integrity manifests"
    )
    verify.add_argument("--root", type=Path, default=PROJECT_ROOT)

    benchmark = subparsers.add_parser(
        "benchmark", help="Regenerate telemetry, replay the case, and write evidence"
    )
    benchmark.add_argument("--root", type=Path, default=PROJECT_ROOT)
    return parser


def _validate(root: Path) -> dict[str, object]:
    root = root.resolve()
    policy = load_policy(root / "config" / "assurance_policy.json")
    assurance_case = read_json(root / "assurance_case" / "uav_runtime_case.json")
    stpa_model = read_json(root / "hazards" / "stpa_model.json")
    validate_assurance_case(assurance_case, stpa_model, policy)
    return {
        "valid": True,
        "case_id": assurance_case["case_id"],
        "top_claim_id": assurance_case["top_claim_id"],
        "claims": len(assurance_case["claims"]),
        "evidence_items": len(assurance_case["evidence"]),
        "monitors": len(policy.monitors),
        "hazards": len(stpa_model["hazards"]),
        "safety_constraints": len(stpa_model["safety_constraints"]),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate":
            result = _validate(args.root)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        if args.command == "benchmark":
            result = run_benchmark(args.root)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0 if result["all_benchmark_checks_passed"] else 2
        if args.command == "verify":
            result = verify_manifest(args.root)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
    except (FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 2
