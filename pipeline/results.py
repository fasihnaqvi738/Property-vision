"""Shared JSON result contract for every capture tier."""


def _unavailable_measurement(unit: str, method: str) -> dict:
    return {
        "status": "unavailable",
        "value": None,
        "unit": unit,
        "interval": None,
        "method": method,
    }


def _unavailable_calibration() -> dict:
    return {
        "status": "unavailable",
        "sample_count": 0,
        "interval_coverage": None,
        "median_error": _unavailable_measurement("m", "No ground-truth benchmark has been run."),
    }


def _serialize_candidate_room_plans(boundary_hypotheses: list[dict]) -> list[dict]:
    """Expose metric-looking boundary faces as review candidates, never accepted rooms."""
    candidates = []
    for hypothesis in boundary_hypotheses:
        method = (
            "Diagnostic room-shaped face from fitted wall intersections; values are provisional "
            "and have no ground-truth-calibrated confidence interval."
        )
        candidates.append({
            "candidate_id": str(hypothesis["candidate_id"]),
            "status": "diagnostic_only",
            "footprint": hypothesis.get("vertices_xy_m", []),
            "floor_area": {
                "status": "partial",
                "value": hypothesis.get("area_m2"),
                "unit": "m^2",
                "interval": None,
                "method": method,
            },
            "walls": [
                {
                    "side_id": f"side_{index}",
                    "length": {
                        "status": "partial",
                        "value": length,
                        "unit": "m",
                        "interval": None,
                        "method": method,
                    },
                    "supporting_wall_candidate_ids": list(
                        hypothesis.get("side_supporting_wall_candidate_ids", [])[index - 1]
                        if len(hypothesis.get("side_supporting_wall_candidate_ids", [])) >= index
                        else hypothesis.get("supporting_wall_candidate_ids", [])
                    ),
                }
                for index, length in enumerate(hypothesis.get("side_lengths_m", []), start=1)
            ],
            "ceiling_height": _unavailable_measurement(
                "m", "No complete, ground-truthed room ceiling plane was identified."
            ),
            "opening_detection_status": "unavailable",
            "supporting_wall_candidate_ids": list(hypothesis.get("supporting_wall_candidate_ids", [])),
        })
    return candidates


def build_result(
    *,
    capture_id: str,
    tier: str,
    source_format: str,
    device: str | None,
    input_files: list[str],
    reconstruction_method: str,
    reconstruction_summary: dict,
    point_cloud: str | None,
    limitations: list[str],
    raw_capture: list[str] | None = None,
    debug_views: list[str] | None = None,
    boundary_hypotheses: list[dict] | None = None,
    drift_handling: dict | None = None,
) -> dict:
    """Build the honest shared envelope; unsupported product outputs stay explicit."""
    return {
        "schema_version": "1.0.0",
        "run_status": "partial",
        "capture": {
            "capture_id": capture_id,
            "tier": tier,
            "source_format": source_format,
            "device": device,
            "input_files": input_files,
        },
        "reconstruction": {
            "status": "complete",
            "method": reconstruction_method,
            "summary": reconstruction_summary,
        },
        "property_plan": {
            "status": "unavailable",
            "coordinate_system": "world frame; metres assumed where sensor poses provide scale",
            "rooms": [],
            "room_candidates": _serialize_candidate_room_plans(boundary_hypotheses or []),
            "boundary_hypotheses": boundary_hypotheses or [],
            "stitched_plan": {
                "status": "unavailable",
                "adjacency": [],
                "footprint": _unavailable_measurement("m^2", "Room footprints have not been extracted."),
                "overlaps": [],
                "candidate_footprints": [],
            },
        },
        "damage_regions": [],
        "concealed_damage_flags": [],
        "scope_line_items": [],
        "quality": {
            "drift_handling": drift_handling or {
                "status": "unavailable",
                "method": "Input poses are used as supplied; loop closure and pose-graph correction are not implemented.",
                "ablation_artifact": None,
            },
            "calibration_by_tier": {
                "photo": _unavailable_calibration(),
                "video": _unavailable_calibration(),
                "lidar": _unavailable_calibration(),
            },
        },
        "artifacts": {
            "rendered_plan": None,
            "point_cloud": point_cloud,
            "raw_capture": raw_capture or [],
            "debug_views": debug_views or [],
        },
        "limitations": limitations,
    }
