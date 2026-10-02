"""Apply human-reviewed damage and scope annotations to a saved pipeline result."""

import json
from pathlib import Path

from pipeline.validation import validate_result


ASSESSMENT_KEYS = {"damage_regions", "concealed_damage_flags", "scope_line_items"}


def apply_assessment(result_path: Path, assessment_path: Path) -> Path:
    """Overlay an explicit human assessment, checking evidence paths and the output schema."""
    result_path = Path(result_path).resolve()
    assessment_path = Path(assessment_path).resolve()
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assessment = json.loads(assessment_path.read_text(encoding="utf-8"))
    if not isinstance(assessment, dict):
        raise ValueError("Assessment sidecar must be a JSON object.")
    unknown = set(assessment) - ASSESSMENT_KEYS
    if unknown:
        raise ValueError(f"Unknown assessment fields: {', '.join(sorted(unknown))}.")

    for key in sorted(ASSESSMENT_KEYS):
        records = assessment.get(key, [])
        if not isinstance(records, list):
            raise ValueError(f"{key} must be an array.")
        result[key] = records

    for region_index, region in enumerate(result["damage_regions"]):
        if not isinstance(region, dict):
            raise ValueError(f"damage_regions[{region_index}] must be an object.")
        for image_index, image_region in enumerate(region.get("image_regions", [])):
            if not isinstance(image_region, dict):
                raise ValueError(f"damage_regions[{region_index}].image_regions[{image_index}] must be an object.")
            image_path = image_region.get("image_path")
            if not isinstance(image_path, str) or not image_path.strip():
                raise ValueError(f"damage_regions[{region_index}].image_regions[{image_index}].image_path is required.")
            resolved_image = Path(image_path)
            if not resolved_image.is_absolute():
                resolved_image = assessment_path.parent / resolved_image
            resolved_image = resolved_image.resolve()
            if not resolved_image.is_file():
                raise FileNotFoundError(f"Assessment evidence image was not found: {resolved_image}")
            image_region["image_path"] = str(resolved_image)
            polygon = image_region.get("polygon_px")
            if not isinstance(polygon, list) or len(polygon) < 3:
                raise ValueError(f"damage_regions[{region_index}].image_regions[{image_index}].polygon_px needs at least three points.")
            for point_index, point in enumerate(polygon):
                if (not isinstance(point, list) or len(point) != 2
                        or any(not isinstance(axis, (int, float)) or isinstance(axis, bool) or axis < 0 for axis in point)):
                    raise ValueError(f"Polygon point {point_index} must be a non-negative [x, y] pixel pair.")

    result["limitations"].append(
        f"Damage labels, concealed-damage rules, and scope quantities were supplied by a human assessment sidecar ({assessment_path}); the capture pipeline did not infer them."
    )
    validate_result(result)
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result_path
