"""Compare Polycam raw and globally optimized pose reconstructions."""

import argparse
import json
import math
from pathlib import Path


def _read_result(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _value(result: dict, *keys):
    node = result
    for key in keys:
        if isinstance(node, dict):
            if key not in node:
                return None
            node = node[key]
        elif isinstance(node, list) and isinstance(key, int) and 0 <= key < len(node):
            node = node[key]
        else:
            return None
    return node


def _numeric_comparison(raw, optimized):
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
               for v in (raw, optimized)):
        return {"raw": raw, "optimized": optimized, "delta": None, "relative_change_percent": None}
    delta = optimized - raw
    return {
        "raw": raw,
        "optimized": optimized,
        "delta": round(delta, 6),
        "relative_change_percent": round(delta / abs(raw) * 100, 3) if raw else None,
    }


def build_report(raw_result: dict, optimized_result: dict, raw_path: Path, optimized_path: Path) -> dict:
    for label, result, expected_mode in (
        ("raw", raw_result, "raw"), ("optimized", optimized_result, "optimized")
    ):
        if _value(result, "capture", "source_format") != "polycam_raw_lidar":
            raise ValueError(f"{label} result is not a Polycam raw LiDAR result.")
        if _value(result, "reconstruction", "summary", "pose_mode") != expected_mode:
            raise ValueError(f"{label} result must have pose_mode={expected_mode!r}.")
    if _value(raw_result, "capture", "capture_id") != _value(optimized_result, "capture", "capture_id"):
        raise ValueError("Raw and optimized results must use the same capture_id.")
    raw_capture = _value(raw_result, "artifacts", "raw_capture") or []
    optimized_capture = _value(optimized_result, "artifacts", "raw_capture") or []
    if not raw_capture or not optimized_capture or {str(Path(p).resolve()).casefold() for p in raw_capture} != {
        str(Path(p).resolve()).casefold() for p in optimized_capture
    }:
        raise ValueError("Raw and optimized results must reference the same raw capture path.")

    metrics = {
        "observed_floor_outline_area_m2": ("floor_return_analysis", "largest_component_coverage_outline", "outline_area_m2"),
        "observed_floor_cell_area_m2": ("floor_return_analysis", "largest_component_coverage_outline", "observed_cell_area_m2"),
        "provisional_floor_level_m": ("floor_return_analysis", "provisional_floor_level_m"),
        "camera_translation_span_x_m": ("floor_return_analysis", "camera_translation_spans_m", 0),
        "camera_translation_span_y_m": ("floor_return_analysis", "camera_translation_spans_m", 1),
        "camera_translation_span_z_m": ("floor_return_analysis", "camera_translation_spans_m", 2),
        "wall_candidate_count": ("wall_plane_analysis", "candidate_count"),
        "floor_aligned_wall_count": ("wall_plane_analysis", "floor_coverage_alignment", "aligned_candidate_count"),
        "boundary_face_hypothesis_count": ("wall_plane_analysis", "room_boundary_hypotheses", "candidate_count"),
        "opening_candidate_count": ("wall_plane_analysis", "opening_analysis", "candidate_count"),
    }
    raw_summary = _value(raw_result, "reconstruction", "summary") or {}
    opt_summary = _value(optimized_result, "reconstruction", "summary") or {}
    return {
        "report_version": "1.0",
        "ablation": "Polycam raw camera poses vs globally optimized camera poses",
        "capture_id": _value(raw_result, "capture", "capture_id"),
        "ground_truth_used": False,
        "accuracy_conclusion": "unavailable_without_independent_ground_truth",
        "interpretation": "Deltas describe changes in pipeline diagnostics only; they do not establish which pose set or geometry is more accurate.",
        "inputs": {"raw_result": str(raw_path.resolve()), "optimized_result": str(optimized_path.resolve())},
        "metrics": {
            name: _numeric_comparison(
                _value(raw_summary, *path), _value(opt_summary, *path)
            ) for name, path in metrics.items()
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", required=True, type=Path, help="result.json generated with --pose-mode raw")
    parser.add_argument("--optimized", required=True, type=Path, help="result.json generated with --pose-mode optimized")
    parser.add_argument("--output", type=Path, help="Report path (default: drift_ablation.json beside optimized result)")
    args = parser.parse_args()
    report = build_report(_read_result(args.raw), _read_result(args.optimized), args.raw, args.optimized)
    output = args.output or args.optimized.parent / "drift_ablation.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Drift ablation report: {output}")


if __name__ == "__main__":
    main()
