from __future__ import annotations

import csv
import hashlib
import html
import json
from pathlib import Path
from typing import Any, Iterable


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: "" if row.get(key) is None else str(row.get(key)).lower()
                    if isinstance(row.get(key), bool)
                    else row.get(key)
                    for key in fieldnames
                }
            )


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(
                    row,
                    sort_keys=True,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
            )
            stream.write("\n")


def _format_metric(value: Any, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.{digits}f}"


def write_markdown_report(path: Path, summaries: list[dict[str, Any]]) -> None:
    lines = [
        "# Runtime Assurance Benchmark",
        "",
        "All inputs are deterministically generated telemetry traces. This is an open-loop regression fixture, not field-flight validation.",
        "All six declared case assumptions remain UNVALIDATED; support labels are conditional predicate results.",
        "",
        "| Scenario | Runs | Expected monitors | Support-loss event | Exact action | p95 policy response | First 1 s oracle coverage | Pre-oracle intervention | Maximum action |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for item in summaries:
        lines.append(
            "| {scenario} | {runs} | {activation} | {detection} | {exact_action} | {policy_time} s | {window_coverage} | {pre_oracle} | {actions} |".format(
                scenario=item["scenario_id"],
                runs=item["runs"],
                activation=_format_metric(item["expected_monitor_activation_rate"]),
                detection=_format_metric(item["support_loss_detection_rate"]),
                exact_action=_format_metric(item["exact_expected_action_rate"]),
                policy_time=_format_metric(item["p95_policy_response_time_s"]),
                window_coverage=_format_metric(
                    item["mean_oracle_first_1s_unsupported_coverage"]
                ),
                pre_oracle=_format_metric(item["mean_pre_oracle_intervention_rate"]),
                actions=", ".join(item["maximum_actions"]),
            )
        )
    lines.extend(
        [
            "",
            "The scenario oracle uses separately configured synthetic criteria. It reduces direct threshold identity for four signal families but is not independent ground truth. Oracle-positive coverage is descriptive and is not an acceptance gate.",
            "",
            "Policy response time begins at the action-trigger monitor's first raw failure and ends only when the exact expected action is selected. More severe but incorrect actions do not count as success. Neither timing metric includes command delivery, actuator response, or vehicle recovery.",
            "",
            "The p95 value uses the nearest-rank definition across seeds.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_svg_dashboard(path: Path, summaries: list[dict[str, Any]]) -> None:
    width = 1220
    row_height = 72
    height = 128 + row_height * len(summaries)
    colors = {"baseline": "#2563eb", "fault": "#dc2626"}
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#f8fafc"/>',
        '<style>text{font-family:Inter,Segoe UI,Arial,sans-serif;fill:#0f172a}.title{font-size:24px;font-weight:700}.sub{font-size:13px;fill:#475569}.head{font-size:12px;font-weight:700;fill:#475569}.label{font-size:13px;font-weight:600}.value{font-size:12px;fill:#334155}</style>',
        '<text x="36" y="40" class="title">Runtime evidence and action-policy benchmark</text>',
        '<text x="36" y="64" class="sub">10 deterministic seeds per scenario; simulated telemetry replay, not flight-test performance</text>',
        '<text x="36" y="100" class="head">SCENARIO</text>',
        '<text x="330" y="100" class="head">SUPPORT-LOSS EVENT</text>',
        '<text x="570" y="100" class="head">P95 POLICY RESPONSE</text>',
        '<text x="820" y="100" class="head">EXACT ACTION RATE</text>',
        '<text x="1040" y="100" class="head">MAX ACTION</text>',
    ]
    for index, item in enumerate(summaries):
        y = 120 + index * row_height
        scenario = html.escape(str(item["scenario_id"]))
        color = colors["baseline" if scenario == "baseline" else "fault"]
        detection = item["support_loss_detection_rate"]
        exact_action = item["exact_expected_action_rate"]
        latency = item["p95_policy_response_time_s"]
        detection_width = 180 * (float(detection) if detection is not None else 0.0)
        action_width = 160 * (float(exact_action) if exact_action is not None else 0.0)
        parts.extend(
            [
                f'<line x1="36" y1="{y + 54}" x2="1184" y2="{y + 54}" stroke="#e2e8f0"/>',
                f'<text x="36" y="{y + 27}" class="label">{scenario}</text>',
                f'<rect x="330" y="{y + 12}" width="180" height="18" rx="4" fill="#e2e8f0"/>',
                f'<rect x="330" y="{y + 12}" width="{detection_width:.1f}" height="18" rx="4" fill="{color}"/>',
                f'<text x="518" y="{y + 27}" class="value">{_format_metric(detection)}</text>',
                f'<text x="570" y="{y + 27}" class="label">{_format_metric(latency)} s</text>',
                f'<rect x="820" y="{y + 12}" width="160" height="18" rx="4" fill="#e2e8f0"/>',
                f'<rect x="820" y="{y + 12}" width="{action_width:.1f}" height="18" rx="4" fill="{color}"/>',
                f'<text x="988" y="{y + 27}" class="value">{_format_metric(exact_action)}</text>',
                f'<text x="1040" y="{y + 27}" class="label">{html.escape(", ".join(item["maximum_actions"]))}</text>',
            ]
        )
    parts.append("</svg>\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(parts), encoding="utf-8", newline="\n")
