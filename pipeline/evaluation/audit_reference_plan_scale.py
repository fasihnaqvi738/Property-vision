"""Check whether traced plan-pixel room spans share one metric scale."""

from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

import numpy as np


def _fit(rows: list[dict], *, anisotropic: bool) -> dict:
    best = None
    for flips in itertools.product((False, True), repeat=len(rows)):
        px_x = np.asarray([row["span_px"][0] for row in rows], dtype=np.float64)
        px_y = np.asarray([row["span_px"][1] for row in rows], dtype=np.float64)
        target_x = np.asarray([
            row["printed_dimensions_m"][1 if flip else 0]
            for row, flip in zip(rows, flips)
        ], dtype=np.float64)
        target_y = np.asarray([
            row["printed_dimensions_m"][0 if flip else 1]
            for row, flip in zip(rows, flips)
        ], dtype=np.float64)

        if anisotropic:
            scale_x = float(px_x @ target_x / (target_x @ target_x))
            scale_y = float(px_y @ target_y / (target_y @ target_y))
            predicted_x, predicted_y = px_x / scale_x, px_y / scale_y
        else:
            observed = np.concatenate((px_x, px_y))
            targets = np.concatenate((target_x, target_y))
            scale_x = scale_y = float(observed @ targets / (targets @ targets))
            predicted_x, predicted_y = px_x / scale_x, px_y / scale_y

        errors_x = (predicted_x - target_x) / target_x
        errors_y = (predicted_y - target_y) / target_y
        errors = np.concatenate((errors_x, errors_y))
        rms_percent = float(np.sqrt(np.mean(errors ** 2)) * 100)
        if best is None or rms_percent < best["rms_dimension_error_percent"]:
            best = {
                "scale_x_px_per_m": scale_x,
                "scale_y_px_per_m": scale_y,
                "rms_dimension_error_percent": rms_percent,
                "mean_absolute_dimension_error_percent": float(np.mean(np.abs(errors)) * 100),
                "max_absolute_dimension_error_percent": float(np.max(np.abs(errors)) * 100),
                "orientation_swaps_by_room": {
                    row["room_id"]: bool(flip) for row, flip in zip(rows, flips)
                },
                "rooms": [
                    {
                        "room_id": row["room_id"],
                        "printed_dimensions_m_assigned_x_y": [float(tx), float(ty)],
                        "traced_bbox_span_px": row["span_px"],
                        "bbox_dimensions_at_fitted_scale_m": [float(mx), float(my)],
                        "relative_error_percent_x_y": [float(ex * 100), float(ey * 100)],
                    }
                    for row, tx, ty, mx, my, ex, ey in zip(
                        rows, target_x, target_y, predicted_x, predicted_y, errors_x, errors_y
                    )
                ],
            }
    return best


def audit_reference_plan_scale(reference_path: Path) -> dict:
    reference_path = Path(reference_path)
    source = json.loads(reference_path.read_text(encoding="utf-8"))
    rows = []
    for space in source.get("rooms", []):
        dimensions = space.get("dimensions_m")
        polygon = space.get("polygon_px", [])
        if (
            not isinstance(dimensions, list)
            or len(dimensions) != 2
            or any(not isinstance(value, (int, float)) or value <= 0 for value in dimensions)
            or len(polygon) < 3
        ):
            continue
        xs = [float(point[0]) for point in polygon]
        ys = [float(point[1]) for point in polygon]
        rows.append({
            "room_id": space["room_id"],
            "span_px": [max(xs) - min(xs), max(ys) - min(ys)],
            "printed_dimensions_m": [float(value) for value in dimensions],
        })
    if not rows:
        raise ValueError("No dimensioned room polygons are available for the scale audit.")

    return {
        "evaluation": "reference-plan global pixel-to-metre scale consistency",
        "reference_plan": reference_path.name,
        "coordinate_frame": source.get("source", {}).get("coordinate_frame"),
        "dimension_policy": source.get("source", {}).get("dimension_truth_policy"),
        "scoring_target_dimensions_are_authoritative": True,
        "scoring_target_source": "Printed room labels, per user instruction",
        "audited_dimensioned_room_count": len(rows),
        "fit_method": "Exhaustive per-room 0/90 degree label orientation assignment; least-squares pixel-per-metre fit to each traced polygon's axis-aligned bounding box.",
        "status": "diagnostic_only",
        "metric_coordinate_calibration": "not_supported_by_one_global_scale",
        "fits": {
            "uniform_scale": _fit(rows, anisotropic=False),
            "independent_x_y_scale": _fit(rows, anisotropic=True),
        },
        "limitations": [
            "Printed values remain authoritative room-dimension targets; this audit only tests whether manually traced drawing polygons are proportionally scaled to them.",
            "The room outlines are manually traced pixel polygons and their bounding boxes are not surveyed geometry.",
            "A low residual would not prove accurate metric room placement; a high residual prevents converting the whole source drawing with one global scale.",
            "This does not evaluate any sensor reconstruction or the unseen walk-in property.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference_plan", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit_reference_plan_scale(args.reference_plan)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    fit = report["fits"]["independent_x_y_scale"]
    print(
        f"Audited {report['audited_dimensioned_room_count']} room polygons: "
        f"best axis-aligned global fit RMS error "
        f"{fit['rms_dimension_error_percent']:.1f}%"
    )
    print(f"Diagnostic report: {args.output}")
    print("Printed dimensions stay authoritative; traced plan coordinates remain pixels.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
