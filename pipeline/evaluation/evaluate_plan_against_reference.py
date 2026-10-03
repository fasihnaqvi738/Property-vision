"""Compare a candidate apartment plan GeoJSON with a traced reference plan.

This evaluator operates in the source floor-plan pixel coordinate frame. It
reports polygon agreement, space overlap, adjacency agreement, and consistency
of copied printed dimensions. A manually traced candidate is explicitly
classified as a self-consistency check, not model accuracy evidence.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read JSON file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object in {path}.")
    return data


def _space_id(properties: dict[str, Any]) -> str | None:
    value = properties.get("room_id") or properties.get("connector_id")
    return str(value) if value is not None else None


def _reference_spaces(reference: dict[str, Any]) -> dict[str, dict[str, Any]]:
    spaces: dict[str, dict[str, Any]] = {}
    for collection in ("rooms", "connectors"):
        items = reference.get(collection, [])
        if not isinstance(items, list):
            raise ValueError(f"Reference {collection} must be an array.")
        for item in items:
            if not isinstance(item, dict):
                raise ValueError(f"Reference {collection} contains a non-object entry.")
            identifier = item.get("room_id") if collection == "rooms" else item.get("connector_id")
            if not isinstance(identifier, str) or not identifier:
                raise ValueError(f"Reference {collection} contains an entry without an ID.")
            if identifier in spaces:
                raise ValueError(f"Duplicate reference space ID: {identifier}.")
            spaces[identifier] = item
    if not spaces:
        raise ValueError("Reference plan has no spaces.")
    return spaces


def _candidate_spaces(candidate: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    features = candidate.get("features")
    if candidate.get("type") != "FeatureCollection" or not isinstance(features, list):
        raise ValueError("Candidate must be a GeoJSON FeatureCollection.")

    spaces: dict[str, dict[str, Any]] = {}
    adjacency_features: list[dict[str, Any]] = []
    for index, feature in enumerate(features):
        if not isinstance(feature, dict) or not isinstance(feature.get("properties"), dict):
            raise ValueError(f"Candidate feature {index} must have a properties object.")
        properties = feature["properties"]
        if properties.get("feature_type") == "room_adjacency":
            adjacency_features.append(feature)
            continue
        identifier = _space_id(properties)
        if identifier is None:
            continue
        if identifier in spaces:
            raise ValueError(f"Duplicate candidate space ID: {identifier}.")
        spaces[identifier] = feature
    if not spaces:
        raise ValueError("Candidate GeoJSON contains no identified space features.")
    return spaces, adjacency_features


def _ring(points: Any, label: str, width: int, height: int) -> np.ndarray:
    try:
        array = np.asarray(points, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} has invalid polygon coordinates.") from exc
    if array.ndim != 2 or array.shape[0] < 4 or array.shape[1] != 2:
        raise ValueError(f"{label} needs a closed polygon ring with at least 3 vertices.")
    if not np.isfinite(array).all():
        raise ValueError(f"{label} has non-finite coordinates.")
    if (array[:, 0] < 0).any() or (array[:, 0] >= width).any() or (array[:, 1] < 0).any() or (array[:, 1] >= height).any():
        raise ValueError(f"{label} has coordinates outside the {width}x{height} reference image.")
    return np.rint(array).astype(np.int32)


def _space_mask(space: dict[str, Any], *, candidate: bool, width: int, height: int, label: str) -> np.ndarray:
    if candidate:
        geometry = space.get("geometry")
        if not isinstance(geometry, dict) or geometry.get("type") != "Polygon":
            raise ValueError(f"Candidate space {label} must have Polygon geometry.")
        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, list) or not coordinates:
            raise ValueError(f"Candidate space {label} has no exterior ring.")
        points = coordinates[0]
    else:
        points = space.get("polygon_px")
    polygon = _ring(points, label, width, height)
    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.fillPoly(mask, [polygon], 1)
    return mask


def _edge_set(edges: Any, *, reference: bool) -> set[tuple[str, str]]:
    if not isinstance(edges, list):
        return set()
    result: set[tuple[str, str]] = set()
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        a_key, b_key = ("space_a", "space_b") if reference else ("space_a", "space_b")
        a, b = edge.get(a_key), edge.get(b_key)
        if isinstance(a, str) and isinstance(b, str):
            result.add(tuple(sorted((a, b))))
    return result


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None or precision + recall == 0:
        return None
    return 2 * precision * recall / (precision + recall)


def _dimension_report(
    reference_spaces: dict[str, dict[str, Any]], candidate_spaces: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    rows = []
    for space_id, reference in reference_spaces.items():
        truth = reference.get("dimensions_m")
        if not isinstance(truth, list):
            continue
        feature = candidate_spaces.get(space_id)
        properties = feature.get("properties", {}) if feature else {}
        predicted = properties.get("dimensions_m") if isinstance(properties, dict) else None
        if not isinstance(predicted, list) or len(predicted) != len(truth):
            rows.append({"space_id": space_id, "reference_m": truth, "candidate_m": predicted, "status": "missing_or_incompatible"})
            continue
        errors = []
        unavailable_axes = 0
        has_mismatch = False
        for expected, actual in zip(truth, predicted):
            if expected is None and actual is None:
                unavailable_axes += 1
            elif isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
                errors.append(abs(float(actual) - float(expected)))
            else:
                has_mismatch = True
        status = (
            "different_or_unscorable" if has_mismatch
            else "consistent" if errors and all(error == 0 for error in errors)
            else "unavailable"
        )
        rows.append({
            "space_id": space_id,
            "reference_m": truth,
            "candidate_m": predicted,
            "absolute_difference_m": errors if errors else None,
            "unavailable_axes": unavailable_axes,
            "status": status,
        })
    scored = [value for row in rows for value in (row.get("absolute_difference_m") or [])]
    return {
        "spaces_with_printed_dimensions": len(rows),
        "spaces_consistent_with_reference_labels": sum(row["status"] == "consistent" for row in rows),
        "mean_absolute_label_difference_m": sum(scored) / len(scored) if scored else None,
        "rows": rows,
        "interpretation": "Copied dimension-label consistency only; these labels are not independently measured truth.",
        "independent_metric_accuracy": "not_scored",
    }


def _source_coverage(reference_path: Path, reference: dict[str, Any], candidate_path: Path) -> dict[str, Any]:
    case_dir = reference_path.parent
    source_manifest_path = case_dir / "source_manifest.json"
    source_manifest = _read_json(source_manifest_path) if source_manifest_path.is_file() else {}
    floor_plan_name = reference.get("source", {}).get("floor_plan_image")
    floor_plan_path = case_dir / floor_plan_name if isinstance(floor_plan_name, str) else None
    photo_groups = []
    for room in reference.get("rooms", []):
        if not isinstance(room, dict):
            continue
        folder = room.get("photo_folder")
        folder_path = (case_dir / folder).resolve() if isinstance(folder, str) else None
        files = sorted(
            str(path.relative_to(case_dir))
            for path in folder_path.rglob("*")
            if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".heic", ".heif"}
        ) if folder_path and folder_path.is_dir() else []
        if files:
            photo_groups.append({"room_id": room.get("room_id"), "photo_count": len(files), "folder": str(folder)})

    video_name = source_manifest.get("walkthrough_video_file")
    video_path = case_dir / video_name if isinstance(video_name, str) else None
    segments_name = source_manifest.get("video_room_segments_file", "video_room_segments.json")
    segments_path = case_dir / segments_name if isinstance(segments_name, str) else None
    segment_count = None
    if segments_path and segments_path.is_file():
        segment_data = _read_json(segments_path)
        segments = segment_data.get("segments", [])
        segment_count = len(segments) if isinstance(segments, list) else None

    lidar_extensions = {".ply", ".e57", ".las", ".laz", ".pcd", ".xyz", ".pts"}
    lidar_files = sorted(
        str(path.relative_to(case_dir))
        for path in case_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in lidar_extensions
    )
    evidence_path = candidate_path.parent.parent / "evidence_report.json"
    evidence = _read_json(evidence_path) if evidence_path.is_file() else {}
    photo_run = evidence.get("photo_run", {})
    photo_joint = photo_run.get("joint_reconstruction", {}) if isinstance(photo_run, dict) else {}
    video_run = evidence.get("video_run", {})
    return {
        "floor_plan": {
            "available": bool(floor_plan_path and floor_plan_path.is_file()),
            "file": str(floor_plan_path) if floor_plan_path else None,
            "role": "manually traced reference drawing; not independently calibrated metric truth",
        },
        "photos": {
            "available": bool(photo_groups),
            "room_group_count": len(photo_groups),
            "image_count": sum(group["photo_count"] for group in photo_groups),
            "groups": photo_groups,
            "reconstruction_run": {
                "groups_processed": photo_run.get("total_room_groups"),
                "registered_photos": photo_run.get("registered_photo_total"),
                "largest_joint_model_coverage_percent": photo_joint.get("largest_model_photo_coverage_percent"),
                "joint_model_is_metric_or_room_segmented": photo_joint.get("is_metric_or_room_segmented"),
                "evidence_report": str(evidence_path) if evidence else None,
            },
        },
        "video": {
            "available": bool(video_path and video_path.is_file()),
            "file": str(video_path) if video_path else None,
            "manually_assigned_room_intervals": segment_count,
            "reconstruction_run": {
                "room_intervals_processed": video_run.get("input_room_intervals"),
                "intervals_with_models": video_run.get("intervals_with_models"),
                "intervals_with_at_least_3_registered_frames": video_run.get("intervals_with_at_least_3_registered_frames"),
                "coordinate_scale": video_run.get("coordinate_scale"),
                "evidence_report": str(evidence_path) if evidence else None,
            },
        },
        "lidar": {
            "available": bool(lidar_files),
            "files": lidar_files,
            "reconstruction_run": "not evidenced for this apartment case",
        },
        "source_manifest_available": source_manifest_path.is_file(),
    }


def evaluate_plan_against_reference(reference_path: Path, candidate_path: Path, output_path: Path | None = None) -> dict[str, Any]:
    reference_path = Path(reference_path).resolve()
    candidate_path = Path(candidate_path).resolve()
    reference = _read_json(reference_path)
    candidate = _read_json(candidate_path)
    reference_source = reference.get("source", {})
    width, height = reference_source.get("image_width_px"), reference_source.get("image_height_px")
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        raise ValueError("Reference plan must declare positive source image_width_px and image_height_px.")
    coordinate_frame = reference_source.get("coordinate_frame")
    if candidate.get("coordinate_reference") != coordinate_frame:
        raise ValueError(
            "Candidate and reference coordinate frames differ: expected "
            f"{coordinate_frame!r}, got {candidate.get('coordinate_reference')!r}."
        )

    truth_spaces = _reference_spaces(reference)
    predicted_spaces, adjacency_features = _candidate_spaces(candidate)
    truth_ids, predicted_ids = set(truth_spaces), set(predicted_spaces)
    matched_ids = sorted(truth_ids & predicted_ids)
    missing_ids, extra_ids = sorted(truth_ids - predicted_ids), sorted(predicted_ids - truth_ids)

    geometry_rows = []
    total_intersection = total_union = 0
    predicted_masks: dict[str, np.ndarray] = {}
    truth_masks: dict[str, np.ndarray] = {}
    for space_id in matched_ids:
        truth_mask = _space_mask(truth_spaces[space_id], candidate=False, width=width, height=height, label=f"reference {space_id}")
        predicted_mask = _space_mask(predicted_spaces[space_id], candidate=True, width=width, height=height, label=f"candidate {space_id}")
        truth_masks[space_id] = truth_mask
        predicted_masks[space_id] = predicted_mask
        intersection = int(np.logical_and(truth_mask, predicted_mask).sum())
        union = int(np.logical_or(truth_mask, predicted_mask).sum())
        truth_area = int(truth_mask.sum())
        prediction_area = int(predicted_mask.sum())
        total_intersection += intersection
        total_union += union
        geometry_rows.append({
            "space_id": space_id,
            "reference_area_px": truth_area,
            "candidate_area_px": prediction_area,
            "intersection_px": intersection,
            "iou": intersection / union if union else None,
        })

    reference_overlaps = []
    candidate_overlaps = []
    all_ids = sorted(truth_ids)
    # Check all declared reference spaces, including any candidate-missed space.
    for index, a in enumerate(all_ids):
        mask_a = truth_masks.get(a)
        if mask_a is None:
            mask_a = _space_mask(truth_spaces[a], candidate=False, width=width, height=height, label=f"reference {a}")
        for b in all_ids[index + 1:]:
            mask_b = truth_masks.get(b)
            if mask_b is None:
                mask_b = _space_mask(truth_spaces[b], candidate=False, width=width, height=height, label=f"reference {b}")
            pixels = int(np.logical_and(mask_a, mask_b).sum())
            if pixels > 4:
                reference_overlaps.append({"space_a": a, "space_b": b, "intersection_px": pixels})
    candidate_ids = sorted(predicted_ids)
    for index, a in enumerate(candidate_ids):
        mask_a = predicted_masks.get(a)
        if mask_a is None:
            mask_a = _space_mask(predicted_spaces[a], candidate=True, width=width, height=height, label=f"candidate {a}")
        for b in candidate_ids[index + 1:]:
            mask_b = predicted_masks.get(b)
            if mask_b is None:
                mask_b = _space_mask(predicted_spaces[b], candidate=True, width=width, height=height, label=f"candidate {b}")
            pixels = int(np.logical_and(mask_a, mask_b).sum())
            if pixels > 4:
                candidate_overlaps.append({"space_a": a, "space_b": b, "intersection_px": pixels})

    expected_edges = _edge_set(reference.get("adjacency", []), reference=True)
    candidate_edges = set()
    for feature in adjacency_features:
        candidate_edges |= _edge_set(feature.get("properties", {}).get("edges"), reference=False)
    true_edges = expected_edges & candidate_edges
    missing_edges, extra_edges = sorted(expected_edges - candidate_edges), sorted(candidate_edges - expected_edges)
    precision = len(true_edges) / len(candidate_edges) if candidate_edges else (1.0 if not expected_edges else 0.0)
    recall = len(true_edges) / len(expected_edges) if expected_edges else (1.0 if not candidate_edges else 0.0)

    geometry_statuses = {
        str(feature.get("properties", {}).get("geometry_status", ""))
        for feature in predicted_spaces.values()
    }
    manual_self_check = bool(geometry_statuses) and geometry_statuses == {"manual_reference_trace"}
    report = {
        "case_id": reference.get("case_id"),
        "status": "self_consistency_only" if manual_self_check else "reference_comparison",
        "candidate_source": "manual reference trace" if manual_self_check else "candidate GeoJSON",
        "inputs": {"reference_plan": str(reference_path), "candidate_geojson": str(candidate_path)},
        "coordinate_frame": {"name": coordinate_frame, "width_px": width, "height_px": height},
        "space_detection": {
            "reference_spaces": len(truth_ids),
            "candidate_spaces": len(predicted_ids),
            "matched_by_id": len(matched_ids),
            "recall": len(matched_ids) / len(truth_ids) if truth_ids else None,
            "precision": len(matched_ids) / len(predicted_ids) if predicted_ids else None,
            "missing_ids": missing_ids,
            "extra_ids": extra_ids,
        },
        "geometry": {
            "matched_space_count": len(geometry_rows),
            "mean_space_iou": sum(row["iou"] for row in geometry_rows if row["iou"] is not None) / len(geometry_rows) if geometry_rows else None,
            "micro_iou": total_intersection / total_union if total_union else None,
            "reference_overlap_pair_count_over_4px": len(reference_overlaps),
            "candidate_overlap_pair_count_over_4px": len(candidate_overlaps),
            "reference_overlaps": reference_overlaps,
            "candidate_overlaps": candidate_overlaps,
            "rows": geometry_rows,
            "interpretation": "Rasterized pixel-space overlap; this is not metric accuracy or a 3D reconstruction score.",
        },
        "adjacency": {
            "reference_edges": len(expected_edges),
            "candidate_edges": len(candidate_edges),
            "correct_edges": len(true_edges),
            "precision": precision,
            "recall": recall,
            "f1": _f1(precision, recall),
            "missing_edges": [list(edge) for edge in missing_edges],
            "extra_edges": [list(edge) for edge in extra_edges],
            "interpretation": "Adjacency is only as reliable as the manually transcribed reference labels.",
        },
        "dimension_labels": _dimension_report(truth_spaces, predicted_spaces),
        "source_coverage": _source_coverage(reference_path, reference, candidate_path),
        "not_established": [
            "independent metric dimension accuracy or raster-to-metre calibration",
            "automated room-boundary inference from photos, video, or LiDAR",
            "automated room adjacency inference from photos or video",
            "door/opening width detection",
            "a metric stitched 3D property model",
        ],
    }
    if output_path is not None:
        output_path = Path(output_path).resolve()
        report["output_json"] = str(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference_plan", type=Path, help="Manual reference annotation JSON.")
    parser.add_argument("candidate_geojson", type=Path, help="Candidate plan GeoJSON in the same source-image pixel frame.")
    parser.add_argument("--output", type=Path, help="Optional JSON report path.")
    args = parser.parse_args()
    report = evaluate_plan_against_reference(args.reference_plan, args.candidate_geojson, args.output)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
