"""Compare a declared case-study fix with before/after benchmark reports."""

import argparse
import hashlib
import json
import math
from pathlib import Path


def _resolve(base: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()


def _required_text(declaration: dict, key: str) -> str:
    value = declaration.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string.")
    return value.strip()


def _existing_files(base: Path, declaration: dict, key: str) -> list[dict]:
    values = declaration.get(key)
    if not isinstance(values, list) or not values:
        raise ValueError(f"{key} must list at least one saved file.")
    artifacts = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} entries must be non-empty paths.")
        path = _resolve(base, value)
        if not path.is_file():
            raise FileNotFoundError(f"{key} file was not found: {path}")
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        digest = hasher.hexdigest()
        artifacts.append({"path": str(path), "sha256": digest})
    return artifacts


def _gate_value(report: dict, gate_name: str, metric_name: str) -> tuple[float, bool | None]:
    gates = report.get("gates")
    gate = gates.get(gate_name) if isinstance(gates, dict) else None
    if not isinstance(gate, dict):
        raise ValueError(f"Benchmark report does not contain gate {gate_name!r}.")
    value = gate.get(metric_name)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError(f"Gate {gate_name!r} has no numeric metric {metric_name!r}.")
    state = gate.get("gate_pass")
    return float(value), state if isinstance(state, bool) else None


def _run_signature(report: dict) -> list[tuple[str, str, str, str]]:
    runs = report.get("run_provenance")
    if not isinstance(runs, list) or not runs:
        raise ValueError("Before/after benchmark reports must include run_provenance.")
    if any(not isinstance(run, dict) for run in runs):
        raise ValueError("Every run_provenance entry must be an object.")
    signature = [(
        str(run.get("tier", "")),
        str(run.get("room_id", "")),
        str(run.get("capture_id", "")),
        str(run.get("repeat_group") or ""),
    ) for run in runs]
    if len(set(signature)) != len(signature):
        raise ValueError("run_provenance entries must uniquely identify each tier/room/capture/repeat.")
    return sorted((
        str(run.get("tier", "")),
        str(run.get("room_id", "")),
        str(run.get("capture_id", "")),
        str(run.get("repeat_group") or ""),
    ) for run in runs if isinstance(run, dict))


def evaluate_fix_declaration(declaration_path: Path) -> dict:
    declaration_path = Path(declaration_path).resolve()
    base = declaration_path.parent
    declaration = json.loads(declaration_path.read_text(encoding="utf-8"))
    if not isinstance(declaration, dict):
        raise ValueError("Fix declaration must be a JSON object.")

    fix_id = _required_text(declaration, "fix_id")
    gate_name = _required_text(declaration, "target_gate")
    metric_name = _required_text(declaration, "target_metric")
    _required_text(declaration, "root_cause_hypothesis")
    _required_text(declaration, "proposed_fix")
    direction = _required_text(declaration, "direction")
    if direction not in {"higher_is_better", "lower_is_better"}:
        raise ValueError("direction must be higher_is_better or lower_is_better.")
    threshold = declaration.get("acceptance_threshold")
    prediction = declaration.get("predicted_after_value")
    for name, value in (("acceptance_threshold", threshold), ("predicted_after_value", prediction)):
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            raise ValueError(f"{name} must be numeric.")

    before_path = _resolve(base, _required_text(declaration, "before_report"))
    after_path = _resolve(base, _required_text(declaration, "after_report"))
    if not before_path.is_file() or not after_path.is_file():
        raise FileNotFoundError("Both before_report and after_report must exist.")
    before_report = json.loads(before_path.read_text(encoding="utf-8"))
    after_report = json.loads(after_path.read_text(encoding="utf-8"))
    if not isinstance(before_report, dict) or not isinstance(after_report, dict):
        raise ValueError("Before and after benchmark reports must be JSON objects.")
    if before_report.get("benchmark_id") != after_report.get("benchmark_id"):
        raise ValueError("Before/after benchmark reports must use the same benchmark_id.")
    if _run_signature(before_report) != _run_signature(after_report):
        raise ValueError("Before/after reports must use the same tier, room, capture, and repeat IDs.")

    before_value, before_gate_pass = _gate_value(before_report, gate_name, metric_name)
    after_value, after_gate_pass = _gate_value(after_report, gate_name, metric_name)
    predicted_delta = float(prediction) - before_value
    actual_delta = after_value - before_value
    direction_sign = 1.0 if direction == "higher_is_better" else -1.0
    improvement = actual_delta * direction_sign
    before_margin = abs(before_value - float(threshold))
    after_margin = abs(after_value - float(threshold))
    threshold_satisfied = (
        after_value >= float(threshold) if direction == "higher_is_better"
        else after_value <= float(threshold)
    )

    commands = declaration.get("regeneration_commands")
    if not isinstance(commands, list) or not commands or any(not isinstance(item, str) or not item.strip() for item in commands):
        raise ValueError("regeneration_commands must contain the exact commands for both runs and the reports.")

    artifacts = {
        "evidence": _existing_files(base, declaration, "evidence_paths"),
        "code_changes": _existing_files(base, declaration, "code_change_paths"),
        "before_runs": _existing_files(base, declaration, "before_run_artifacts"),
        "after_runs": _existing_files(base, declaration, "after_run_artifacts"),
    }
    return {
        "fix_id": fix_id,
        "benchmark_id": before_report.get("benchmark_id"),
        "target_gate": gate_name,
        "target_metric": metric_name,
        "direction": direction,
        "acceptance_threshold": float(threshold),
        "before": {
            "report": str(before_path),
            "value": before_value,
            "gate_pass": before_gate_pass,
            "distance_from_threshold": before_margin,
        },
        "prediction": {
            "value": float(prediction),
            "predicted_delta": predicted_delta,
        },
        "after": {
            "report": str(after_path),
            "value": after_value,
            "gate_pass": after_gate_pass,
            "actual_delta": actual_delta,
            "improvement_in_declared_direction": improvement > 0,
            "distance_from_threshold": after_margin,
            "moved_toward_threshold": after_margin < before_margin,
            "threshold_satisfied": threshold_satisfied,
        },
        "prediction_absolute_error": abs(after_value - float(prediction)),
        "fix_loop_gate_pass": after_gate_pass is True and threshold_satisfied,
        "artifacts": artifacts,
        "regeneration_commands": commands,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the case-study before/after fix loop.")
    parser.add_argument("declaration", type=Path, help="Completed fix declaration JSON.")
    parser.add_argument("--output", type=Path, help="Report path (default: fix_loop_report.json beside the declaration).")
    args = parser.parse_args()
    report = evaluate_fix_declaration(args.declaration)
    output = args.output or args.declaration.resolve().parent / "fix_loop_report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    after = report["after"]
    print(f"Fix loop report: {output}")
    print(f"Target: {report['target_gate']}.{report['target_metric']}")
    print(f"Before: {report['before']['value']}  Predicted: {report['prediction']['value']}  After: {after['value']}")
    print(f"Gate: {'PASS' if report['fix_loop_gate_pass'] else 'FAIL/UNVERIFIED'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
