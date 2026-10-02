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
            "boundary_hypotheses": boundary_hypotheses or [],
            "stitched_plan": {
                "status": "unavailable",
                "adjacency": [],
                "footprint": _unavailable_measurement("m^2", "Room footprints have not been extracted."),
                "overlaps": [],
            },
        },
        "damage_regions": [],
        "concealed_damage_flags": [],
        "scope_line_items": [],
        "quality": {
            "drift_handling": {
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
