from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import read_json
from .reporting import sha256_file
from .simulation import read_trace


def _resolved_child(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Manifest path escapes project root: {relative}")
    return path


def _verify_entries(
    root: Path, entries: list[dict[str, Any]], *, required_parent: Path | None = None
) -> set[str]:
    verified_paths: set[str] = set()
    for entry in entries:
        relative = str(entry["path"])
        if relative in verified_paths:
            raise ValueError(f"Duplicate manifest path: {relative}")
        verified_paths.add(relative)
        path = _resolved_child(root, relative)
        if required_parent is not None and not path.is_relative_to(required_parent):
            raise ValueError(f"Manifest entry is outside {required_parent.name}: {relative}")
        if not path.is_file():
            raise ValueError(f"Manifest file is missing: {relative}")
        if sha256_file(path) != str(entry["sha256"]):
            raise ValueError(f"SHA-256 mismatch: {relative}")
        if "bytes" in entry and path.stat().st_size != int(entry["bytes"]):
            raise ValueError(f"Byte-size mismatch: {relative}")
    return verified_paths


def _expected_source_paths(root: Path) -> set[str]:
    paths = {
        root / "config" / "assurance_policy.json",
        root / "assurance_case" / "uav_runtime_case.json",
        root / "hazards" / "stpa_model.json",
        root / "experiments" / "benchmark_config.json",
        root / "pyproject.toml",
        *set((root / "runtime_assurance").rglob("*.py")),
    }
    return {path.relative_to(root).as_posix() for path in paths}


def verify_manifest(root: Path) -> dict[str, Any]:
    root = root.resolve()
    manifest_path = root / "data" / "generated" / "manifest.json"
    manifest = read_json(manifest_path)
    sources = manifest.get("source_files", [])
    traces = manifest.get("traces", [])
    if int(manifest.get("trace_count", -1)) != len(traces):
        raise ValueError("Manifest trace_count does not match trace entries")

    source_paths = _verify_entries(root, sources)
    expected_sources = _expected_source_paths(root)
    if source_paths != expected_sources:
        raise ValueError(
            "Source manifest coverage mismatch: "
            f"missing={sorted(expected_sources - source_paths)}, "
            f"unexpected={sorted(source_paths - expected_sources)}"
        )
    trace_paths = _verify_entries(root, traces)
    actual_trace_paths = {
        path.relative_to(root).as_posix()
        for path in (root / "data" / "generated" / "traces").rglob("*.csv")
    }
    if trace_paths != actual_trace_paths:
        raise ValueError("Trace manifest does not cover the exact generated trace set")
    if source_paths.intersection(trace_paths):
        raise ValueError("A file cannot be both a source and a generated trace")
    for entry in traces:
        path = _resolved_child(root, str(entry["path"]))
        if len(read_trace(path)) != int(entry["rows"]):
            raise ValueError(f"Row-count mismatch: {entry['path']}")

    data_manifest_hash = sha256_file(manifest_path)
    summary_path = root / "results" / "benchmark_summary.json"
    summary = read_json(summary_path)
    if str(summary.get("data_manifest_sha256", "")) != data_manifest_hash:
        raise ValueError("Benchmark summary is not bound to the current data manifest")

    result_manifest_path = root / "results" / "result_manifest.json"
    result_manifest = read_json(result_manifest_path)
    results = result_manifest.get("results", [])
    if int(result_manifest.get("result_count", -1)) != len(results):
        raise ValueError("Result manifest result_count does not match result entries")
    if str(result_manifest.get("data_manifest_sha256", "")) != data_manifest_hash:
        raise ValueError("Result manifest is not bound to the current data manifest")
    result_paths = _verify_entries(root, results, required_parent=(root / "results"))
    if "results/result_manifest.json" in result_paths:
        raise ValueError("Result manifest must not hash itself")
    actual_result_paths = {
        path.relative_to(root).as_posix()
        for path in (root / "results").rglob("*")
        if path.is_file() and path.resolve() != result_manifest_path.resolve()
    }
    if result_paths != actual_result_paths:
        raise ValueError(
            "Result manifest coverage mismatch: "
            f"missing={sorted(actual_result_paths - result_paths)}, "
            f"unexpected={sorted(result_paths - actual_result_paths)}"
        )
    if "results/benchmark_summary.json" not in result_paths:
        raise ValueError("Result manifest does not cover benchmark_summary.json")

    return {
        "valid": True,
        "source_files_verified": len(sources),
        "traces_verified": len(traces),
        "results_verified": len(results),
        "data_manifest_sha256": data_manifest_hash,
        "result_manifest_sha256": sha256_file(result_manifest_path),
        "summary_binding_verified": True,
        "result_binding_verified": True,
    }
