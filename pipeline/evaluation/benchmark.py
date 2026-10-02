"""Score saved Property Vision runs against manually measured benchmark data.

The evaluator is deliberately independent of reconstruction dependencies so it
can replay saved result.json files with the Python standard library alone.
Ground-truth-to-prediction IDs are human-reviewed correspondences; unmatched
opening predictions and missed ground-truth openings count against detection.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path


OPENING_ABS_TOLERANCE_M = 0.02
OPENING_REQUIRED_RATE = 0.85
CEILING_ABS_TOLERANCE_M = 0.015
CEILING_REPEAT_TOLERANCE_M = 0.01
PHOTO_WALL_REL_TOLERANCE = 0.08
VIDEO_WALL_REL_TOLERANCE = 0.03
PHOTO_FOOTPRINT_REL_TOLERANCE = 0.08
VIDEO_FOOTPRINT_REL_TOLERANCE = 0.03


def _measurement(container: dict | None, key: str) -> dict | None:
    if not isinstance(container, dict):
        return None
    value = container.get(key)
    return value if isinstance(value, dict) else None


def _number(measurement: dict | None) -> float | None:
    if not measurement or measurement.get("status") not in {"complete", "partial"}:
        return None
    value = measurement.get("value")
    return float(value) if isinstance(value, (int, float)) else None


def _interval_contains(measurement: dict | None, ground_truth: float) -> bool | None:
    interval = measurement.get("interval") if measurement else None
    if not isinstance(interval, dict):
        return None
    lower, upper = interval.get("lower"), interval.get("upper")
    if not isinstance(lower, (int, float)) or not isinstance(upper, (int, float)):
        return None
    return float(lower) <= ground_truth <= float(upper)


def _index(items: list[dict], key: str) -> dict[str, dict]:
    return {str(item[key]): item for item in items if isinstance(item, dict) and key in item}


def _result_path(manifest_path: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (manifest_path.parent / path).resolve()


def _validate_manifest(manifest: dict, manifest_path: Path) -> None:
    """Fail early with actionable errors instead of opaque KeyError/lookup failures."""
    errors = []
    if not isinstance(manifest, dict):
        raise ValueError("Benchmark manifest must be a JSON object.")
    if not isinstance(manifest.get("benchmark_id"), str) or not manifest["benchmark_id"].strip():
        errors.append("benchmark_id must be a non-empty string.")
    property_truth = manifest.get("property", {})
    if not isinstance(property_truth, dict):
        errors.append("property must be an object.")
    else:
        footprint = property_truth.get("footprint_m2")
        if footprint is not None and (
            not isinstance(footprint, (int, float)) or isinstance(footprint, bool) or footprint <= 0
        ):
            errors.append("property.footprint_m2 must be a positive number or null.")
        adjacency = property_truth.get("adjacency", [])
        if not isinstance(adjacency, list):
            errors.append("property.adjacency must be an array.")
        else:
            for edge_index, edge in enumerate(adjacency):
                if not isinstance(edge, dict) or not isinstance(edge.get("room_a"), str) or not isinstance(edge.get("room_b"), str):
                    errors.append(f"property.adjacency[{edge_index}] must include string room_a and room_b IDs.")
        connector_ids = property_truth.get("connector_room_ids", [])
        if not isinstance(connector_ids, list) or any(not isinstance(room_id, str) for room_id in connector_ids):
            errors.append("property.connector_room_ids must be an array of room ID strings.")
    rooms = manifest.get("ground_truth_rooms")
    if not isinstance(rooms, list) or not rooms:
        errors.append("ground_truth_rooms must be a non-empty array.")
        rooms = []
    room_ids = set()
    for index, room in enumerate(rooms):
        label = f"ground_truth_rooms[{index}]"
        if not isinstance(room, dict):
            errors.append(f"{label} must be an object.")
            continue
        room_id = room.get("room_id")
        if not isinstance(room_id, str) or not room_id.strip():
            errors.append(f"{label}.room_id must be a non-empty string.")
        elif room_id in room_ids:
            errors.append(f"Duplicate room_id: {room_id}.")
        else:
            room_ids.add(room_id)
        for collection in ("walls", "openings"):
            if not isinstance(room.get(collection, []), list):
                errors.append(f"{label}.{collection} must be an array.")
            else:
                id_key, value_key = ("wall_id", "length_m") if collection == "walls" else ("opening_id", "width_m")
                seen = set()
                for item_index, item in enumerate(room.get(collection, [])):
                    item_label = f"{label}.{collection}[{item_index}]"
                    if not isinstance(item, dict):
                        errors.append(f"{item_label} must be an object.")
                        continue
                    item_id, value = item.get(id_key), item.get(value_key)
                    if not isinstance(item_id, str) or not item_id.strip():
                        errors.append(f"{item_label}.{id_key} must be a non-empty string.")
                    elif item_id in seen:
                        errors.append(f"Duplicate {id_key} in {label}: {item_id}.")
                    else:
                        seen.add(item_id)
                    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
                        errors.append(f"{item_label}.{value_key} must be a positive number.")
        for key in ("ceiling_height_m", "floor_area_m2"):
            value = room.get(key)
            if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0):
                errors.append(f"{label}.{key} must be a positive number or null.")

    runs = manifest.get("runs")
    if not isinstance(runs, list):
        errors.append("runs must be an array.")
        runs = []
    for index, run in enumerate(runs):
        label = f"runs[{index}]"
        if not isinstance(run, dict):
            errors.append(f"{label} must be an object.")
            continue
        if run.get("tier") not in {"photo", "video", "lidar"}:
            errors.append(f"{label}.tier must be photo, video, or lidar.")
        if str(run.get("room_id", "")) not in room_ids:
            errors.append(f"{label}.room_id must match a declared ground-truth room_id.")
        result_json = run.get("result_json")
        if not isinstance(result_json, str) or not result_json.strip():
            errors.append(f"{label}.result_json must point to a saved result.json.")
        elif not _result_path(manifest_path, result_json).is_file():
            errors.append(f"{label}.result_json was not found: {_result_path(manifest_path, result_json)}")
        for collection in ("wall_matches", "opening_matches"):
            if collection in run and not isinstance(run[collection], list):
                errors.append(f"{label}.{collection} must be an array.")
        candidate_matches = run.get("boundary_hypothesis_matches", [])
        if not isinstance(candidate_matches, list):
            errors.append(f"{label}.boundary_hypothesis_matches must be an array.")
        side_matches = run.get("boundary_side_matches", [])
        if not isinstance(side_matches, list):
            errors.append(f"{label}.boundary_side_matches must be an array.")
        if "phantom_opening_prediction_ids" in run and not isinstance(run["phantom_opening_prediction_ids"], list):
            errors.append(f"{label}.phantom_opening_prediction_ids must be an array.")
        if "room_matches" in run and not isinstance(run["room_matches"], dict):
            errors.append(f"{label}.room_matches must be an object.")
        for collection, keys in (("wall_matches", ("ground_truth_wall_id", "prediction_surface_id")),
                                 ("opening_matches", ("ground_truth_opening_id", "prediction_opening_id")),
                                 ("boundary_hypothesis_matches", ("ground_truth_room_id", "prediction_candidate_id")),
                                 ("boundary_side_matches", ("ground_truth_room_id", "ground_truth_wall_id", "prediction_candidate_id", "candidate_side_index"))):
            matches = run.get(collection, [])
            if not isinstance(matches, list):
                continue
            for match_index, match in enumerate(matches):
                if not isinstance(match, dict) or any(key not in match for key in keys):
                    errors.append(f"{label}.{collection}[{match_index}] must include {', '.join(keys)}.")
                else:
                    truth_room_id = str(match.get("ground_truth_room_id", ""))
                    if collection in {"boundary_hypothesis_matches", "boundary_side_matches"} and truth_room_id not in room_ids:
                        errors.append(f"{label}.{collection}[{match_index}].ground_truth_room_id must match a declared room_id.")
                    if collection == "boundary_side_matches":
                        side_index = match.get("candidate_side_index")
                        if not isinstance(side_index, int) or isinstance(side_index, bool) or side_index < 0:
                            errors.append(f"{label}.{collection}[{match_index}].candidate_side_index must be a non-negative integer.")
                        truth_room = next((room for room in rooms if isinstance(room, dict) and room.get("room_id") == truth_room_id), {})
                        wall_ids = {str(wall.get("wall_id")) for wall in truth_room.get("walls", []) if isinstance(wall, dict)}
                        if str(match.get("ground_truth_wall_id")) not in wall_ids:
                            errors.append(f"{label}.{collection}[{match_index}].ground_truth_wall_id must match a wall in its room.")
    damage_examples = manifest.get("staged_damage_examples", [])
    if not isinstance(damage_examples, list):
        errors.append("staged_damage_examples must be an array.")
    else:
        for index, example in enumerate(damage_examples):
            label = f"staged_damage_examples[{index}]"
            if not isinstance(example, dict):
                errors.append(f"{label} must be an object.")
                continue
            if not isinstance(example.get("room_id"), str) or example["room_id"] not in room_ids:
                errors.append(f"{label}.room_id must match a declared room_id.")
            if not isinstance(example.get("damage_class"), str) or not example["damage_class"].strip():
                errors.append(f"{label}.damage_class must be a non-empty string.")
            extent = example.get("extent_m2")
            if extent is not None and (not isinstance(extent, (int, float)) or isinstance(extent, bool) or extent <= 0):
                errors.append(f"{label}.extent_m2 must be a positive number or null.")
            if not isinstance(example.get("surface_id"), str) or not example["surface_id"].strip():
                errors.append(f"{label}.surface_id must be a non-empty string.")
            regions = example.get("regions", [])
            if not isinstance(regions, list):
                errors.append(f"{label}.regions must be an array.")
            else:
                for region_index, region in enumerate(regions):
                    region_label = f"{label}.regions[{region_index}]"
                    polygon = region.get("polygon_px") if isinstance(region, dict) else None
                    if not isinstance(region, dict) or not isinstance(region.get("image_path"), str):
                        errors.append(f"{region_label} must include image_path and polygon_px.")
                        continue
                    if not isinstance(polygon, list) or len(polygon) < 3 or any(
                        not isinstance(point, list) or len(point) != 2
                        or any(not isinstance(value, (int, float)) or isinstance(value, bool) for value in point)
                        for point in polygon
                    ):
                        errors.append(f"{region_label}.polygon_px must have at least three [x, y] pixel points.")
    if errors:
        raise ValueError("Invalid benchmark manifest:\n- " + "\n- ".join(errors))


def _benchmark_readiness(manifest: dict) -> dict:
    """Show evidence coverage independently from metric-accuracy scores."""
    rooms = manifest.get("ground_truth_rooms", [])
    room_ids = {room.get("room_id") for room in rooms if isinstance(room, dict)}
    property_truth = manifest.get("property", {})
    connector_ids = set(property_truth.get("connector_room_ids", [])) if isinstance(property_truth, dict) else set()
    habitable_rooms = room_ids - connector_ids
    runs = manifest.get("runs", [])
    tiers = {"photo", "video", "lidar"}
    tier_rooms = {
        tier: {str(run.get("room_id")) for run in runs if run.get("tier") == tier}
        for tier in tiers
    }
    repeated = defaultdict(int)
    for run in runs:
        if run.get("repeat_group"):
            repeated[(str(run.get("room_id")), str(run.get("tier")), str(run["repeat_group"]))] += 1
    damage_examples = manifest.get("staged_damage_examples", [])
    damage_classes = {
        str(example.get("damage_class", "")).strip()
        for example in damage_examples if isinstance(example, dict) and example.get("damage_class")
    }
    measured_rooms = [
        room for room in rooms if isinstance(room, dict)
        and isinstance(room.get("ceiling_height_m"), (int, float))
        and isinstance(room.get("floor_area_m2"), (int, float))
        and room.get("walls")
        and all(isinstance(wall, dict) and isinstance(wall.get("length_m"), (int, float)) for wall in room["walls"])
    ]
    common_tier_rooms = room_ids.intersection(*(tier_rooms[tier] for tier in tiers)) if tiers else set()
    checks = {
        "room_set": {
            "passed": len(habitable_rooms) >= 3 and bool(connector_ids & room_ids),
            "rooms": len(habitable_rooms), "required_rooms": 3,
            "connector_ids": sorted(connector_ids & room_ids),
            "detail": "Requires at least three rooms and one declared connector/hall.",
        },
        "measured_ground_truth": {
            "passed": (
                len(measured_rooms) == len(room_ids)
                and isinstance(property_truth, dict)
                and isinstance(property_truth.get("footprint_m2"), (int, float))
                and bool(property_truth.get("adjacency"))
                and any(room.get("openings") for room in rooms if isinstance(room, dict))
            ),
            "rooms_with_area_ceiling_and_wall_lengths": len(measured_rooms),
            "rooms_declared": len(room_ids),
            "property_footprint_measured": isinstance(property_truth, dict) and isinstance(property_truth.get("footprint_m2"), (int, float)),
            "adjacency_edges": len(property_truth.get("adjacency", [])) if isinstance(property_truth, dict) else 0,
            "detail": "Requires measured room area, ceiling height, wall lengths, property footprint/adjacency, and at least one measured opening.",
        },
        "same_rooms_all_tiers": {
            "passed": bool(room_ids) and common_tier_rooms == room_ids,
            "rooms_with_photo_video_lidar": sorted(common_tier_rooms),
            "rooms_missing_any_tier": sorted(room_ids - common_tier_rooms),
        },
        "repeat_capture": {
            "passed": any(count >= 2 for count in repeated.values()),
            "repeat_groups_with_two_or_more_runs": sum(count >= 2 for count in repeated.values()),
        },
        "staged_damage": {
            "passed": len(damage_examples) >= 2 and len(damage_classes) >= 2
            and all(
                isinstance(example, dict)
                and isinstance(example.get("surface_id"), str) and bool(example["surface_id"].strip())
                and isinstance(example.get("extent_m2"), (int, float))
                and not isinstance(example.get("extent_m2"), bool) and example["extent_m2"] > 0
                and isinstance(example.get("regions"), list) and bool(example["regions"])
                and all(
                    isinstance(region, dict)
                    and isinstance(region.get("image_path"), str) and bool(region["image_path"].strip())
                    and isinstance(region.get("polygon_px"), list) and len(region["polygon_px"]) >= 3
                    and all(
                        isinstance(point, list) and len(point) == 2
                        and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in point)
                        for point in region["polygon_px"]
                    )
                    for region in example["regions"]
                )
                for example in damage_examples
            ),
            "labeled_examples": len(damage_examples),
            "distinct_classes": sorted(damage_classes),
            "detail": "Requires two measured examples from different classes, each tied to a surface and an image polygon.",
        },
    }
    return {"ready": all(check["passed"] for check in checks.values()), "checks": checks}


def _record_metric(rows: list[dict], *, tier: str, capture_id: str, room_id: str,
                   metric: str, object_id: str, ground_truth: float,
                   prediction: dict | None, tolerance: float | None = None,
                   relative: bool = False) -> dict:
    predicted = _number(prediction)
    error = abs(predicted - ground_truth) if predicted is not None else None
    relative_error = error / abs(ground_truth) if error is not None and ground_truth else None
    compare_error = relative_error if relative else error
    passed = compare_error <= tolerance if compare_error is not None and tolerance is not None else None
    row = {
        "tier": tier,
        "capture_id": capture_id,
        "room_id": room_id,
        "metric": metric,
        "object_id": object_id,
        "ground_truth": ground_truth,
        "prediction": predicted,
        "absolute_error": error,
        "relative_error": relative_error,
        "interval_contains_ground_truth": _interval_contains(prediction, ground_truth),
        "gate_tolerance": tolerance,
        "gate_tolerance_kind": "relative" if relative else "absolute",
        "gate_pass": passed,
    }
    rows.append(row)
    return row


def evaluate(manifest_path: Path) -> dict:
    manifest_path = manifest_path.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _validate_manifest(manifest, manifest_path)
    rooms = _index(manifest.get("ground_truth_rooms", []), "room_id")
    runs = manifest.get("runs", [])
    property_truth = manifest.get("property", {})
    metric_rows: list[dict] = []
    opening_totals = defaultdict(lambda: {"ground_truth": 0, "phantoms": 0, "within_tolerance": 0})
    repeat_groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    property_rows = []
    video_footprint_rows = []
    candidate_area_rows = []
    candidate_wall_rows = []

    loaded_runs = []
    for run in runs:
        result_path = _result_path(manifest_path, run["result_json"])
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if not isinstance(result, dict) or not isinstance(result.get("capture"), dict):
            raise ValueError(f"Result must contain a capture object: {result_path}")
        tier = run["tier"]
        capture_id = run.get("capture_id", result.get("capture", {}).get("capture_id", result_path.stem))
        gt_room_id = str(run["room_id"])
        gt_room = rooms[gt_room_id]
        result_rooms = _index(result.get("property_plan", {}).get("rooms", []), "room_id")
        predicted_room_id = str(run.get("prediction_room_id", gt_room_id))
        predicted_room = result_rooms.get(predicted_room_id, {})
        loaded = {"run": run, "result": result, "gt_room": gt_room,
                  "predicted_room": predicted_room, "tier": tier,
                  "capture_id": str(capture_id), "room_id": gt_room_id}
        loaded_runs.append(loaded)

        candidate_index = _index(
            result.get("property_plan", {}).get("boundary_hypotheses", []), "candidate_id"
        )
        for match in run.get("boundary_hypothesis_matches", []):
            truth_room_id = str(match["ground_truth_room_id"])
            truth_room = rooms[truth_room_id]
            ground_truth_area = truth_room.get("floor_area_m2")
            candidate_id = str(match["prediction_candidate_id"])
            candidate = candidate_index.get(candidate_id)
            if candidate is None:
                raise ValueError(
                    f"Boundary hypothesis {candidate_id!r} was not found in {result_path}."
                )
            if isinstance(ground_truth_area, (int, float)) and isinstance(candidate.get("area_m2"), (int, float)):
                error = abs(float(candidate["area_m2"]) - float(ground_truth_area))
                candidate_area_rows.append({
                    "tier": tier,
                    "capture_id": str(capture_id),
                    "room_id": truth_room_id,
                    "candidate_id": candidate_id,
                    "ground_truth_area_m2": float(ground_truth_area),
                    "diagnostic_candidate_area_m2": float(candidate["area_m2"]),
                    "absolute_error_m2": error,
                    "relative_error": error / abs(float(ground_truth_area)) if ground_truth_area else None,
                    "accepted_room_measurement": False,
                    "gate_pass": None,
                })
        for match in run.get("boundary_side_matches", []):
            truth_room_id = str(match["ground_truth_room_id"])
            truth_room = rooms[truth_room_id]
            truth_wall_id = str(match["ground_truth_wall_id"])
            truth_wall = _index(truth_room.get("walls", []), "wall_id").get(truth_wall_id)
            candidate_id = str(match["prediction_candidate_id"])
            candidate = candidate_index.get(candidate_id)
            if candidate is None:
                raise ValueError(f"Boundary hypothesis {candidate_id!r} was not found in {result_path}.")
            side_index = match["candidate_side_index"]
            side_lengths = candidate.get("side_lengths_m", [])
            if side_index >= len(side_lengths):
                raise ValueError(
                    f"Candidate side index {side_index} is out of range for hypothesis {candidate_id!r} in {result_path}."
                )
            predicted_length = side_lengths[side_index]
            truth_length = truth_wall.get("length_m") if truth_wall else None
            if isinstance(truth_length, (int, float)) and isinstance(predicted_length, (int, float)):
                error = abs(float(predicted_length) - float(truth_length))
                candidate_wall_rows.append({
                    "tier": tier,
                    "capture_id": str(capture_id),
                    "room_id": truth_room_id,
                    "ground_truth_wall_id": truth_wall_id,
                    "candidate_id": candidate_id,
                    "candidate_side_index": side_index,
                    "ground_truth_length_m": float(truth_length),
                    "diagnostic_candidate_length_m": float(predicted_length),
                    "absolute_error_m": error,
                    "relative_error": error / abs(float(truth_length)) if truth_length else None,
                    "accepted_wall_measurement": False,
                    "gate_pass": None,
                })

        ceiling_gt = gt_room.get("ceiling_height_m")
        if isinstance(ceiling_gt, (int, float)):
            row = _record_metric(
                metric_rows, tier=tier, capture_id=str(capture_id), room_id=gt_room_id,
                metric="ceiling_height_m", object_id=gt_room_id,
                ground_truth=float(ceiling_gt),
                prediction=_measurement(predicted_room, "ceiling_height"),
                tolerance=CEILING_ABS_TOLERANCE_M,
            )
            repeat_group = run.get("repeat_group")
            if repeat_group:
                repeat_groups[(str(repeat_group), tier, "ceiling_height_m")].append(row)

        for metric_key, gt_key, pred_key in (("floor_area_m2", "floor_area_m2", "floor_area"),):
            gt_value = gt_room.get(gt_key)
            if isinstance(gt_value, (int, float)):
                _record_metric(metric_rows, tier=tier, capture_id=str(capture_id), room_id=gt_room_id,
                               metric=metric_key, object_id=gt_room_id, ground_truth=float(gt_value),
                               prediction=_measurement(predicted_room, pred_key))

        gt_walls = _index(gt_room.get("walls", []), "wall_id")
        predicted_walls = _index(predicted_room.get("walls", []), "surface_id")
        wall_matches = {str(m["ground_truth_wall_id"]): str(m["prediction_surface_id"])
                        for m in run.get("wall_matches", [])}
        for wall_id, gt_wall in gt_walls.items():
            prediction_wall = predicted_walls.get(wall_matches.get(wall_id, ""), {})
            tolerance = {"photo": PHOTO_WALL_REL_TOLERANCE, "video": VIDEO_WALL_REL_TOLERANCE}.get(tier)
            _record_metric(
                metric_rows, tier=tier, capture_id=str(capture_id), room_id=gt_room_id,
                metric="wall_length_m", object_id=wall_id,
                ground_truth=float(gt_wall["length_m"]),
                prediction=_measurement(prediction_wall, "length"),
                tolerance=tolerance, relative=True,
            )

        gt_openings = _index(gt_room.get("openings", []), "opening_id")
        predicted_openings = _index(predicted_room.get("openings", []), "opening_id")
        opening_matches = {str(m["ground_truth_opening_id"]): m.get("prediction_opening_id")
                           for m in run.get("opening_matches", [])}
        opening_totals[tier]["ground_truth"] += len(gt_openings)
        opening_totals[tier]["phantoms"] += len(run.get("phantom_opening_prediction_ids", []))
        for opening_id, gt_opening in gt_openings.items():
            pred_id = opening_matches.get(opening_id)
            pred_opening = predicted_openings.get(str(pred_id), {}) if pred_id else {}
            row = _record_metric(
                metric_rows, tier=tier, capture_id=str(capture_id), room_id=gt_room_id,
                metric="opening_width_m", object_id=opening_id,
                ground_truth=float(gt_opening["width_m"]),
                prediction=_measurement(pred_opening, "width"),
                tolerance=OPENING_ABS_TOLERANCE_M,
            )
            if row["gate_pass"]:
                opening_totals[tier]["within_tolerance"] += 1

        if run.get("repeat_group"):
            repeat_groups[(str(run["repeat_group"]), tier, "wall_lengths")].append({
                "run": loaded, "gt_walls": gt_walls, "predicted_walls": predicted_walls,
                "wall_matches": wall_matches,
            })

    repeatability = []
    for (group_id, tier, metric), samples in repeat_groups.items():
        if len(samples) < 2:
            continue
        if metric == "ceiling_height_m":
            values = [row["prediction"] for row in samples if row["prediction"] is not None]
            spread = max(values) - min(values) if len(values) >= 2 else None
            repeatability.append({
                "repeat_group": group_id, "tier": tier, "metric": metric,
                "capture_count": len(samples), "spread_m": spread,
                "tolerance_m": CEILING_REPEAT_TOLERANCE_M,
                "gate_pass": spread <= CEILING_REPEAT_TOLERANCE_M if spread is not None else False,
            })
        else:
            gt_ids = set.intersection(*(set(sample["gt_walls"]) for sample in samples)) if samples else set()
            for wall_id in sorted(gt_ids):
                gt_length = float(samples[0]["gt_walls"][wall_id]["length_m"])
                values = []
                for sample in samples:
                    pred_id = sample["wall_matches"].get(wall_id)
                    pred = sample["predicted_walls"].get(pred_id, {}) if pred_id else {}
                    value = _number(_measurement(pred, "length"))
                    if value is not None:
                        values.append(value)
                spread = max(values) - min(values) if len(values) >= 2 else None
                tolerance = max(0.01, 0.005 * gt_length)
                repeatability.append({
                    "repeat_group": group_id, "tier": tier, "metric": "wall_length_m",
                    "object_id": wall_id, "capture_count": len(samples), "spread_m": spread,
                    "tolerance_m": tolerance,
                    "gate_pass": spread <= tolerance if spread is not None else False,
                })

    for loaded in loaded_runs:
        tier = loaded["tier"]
        if tier not in {"photo", "video"} or not property_truth:
            continue
        result = loaded["result"]
        stitched = result.get("property_plan", {}).get("stitched_plan", {})
        footprint_gt = property_truth.get("footprint_m2")
        footprint_measurement = _measurement(stitched, "footprint")
        if not isinstance(footprint_gt, (int, float)) or not footprint_gt:
            continue
        footprint_tolerance = (
            PHOTO_FOOTPRINT_REL_TOLERANCE if tier == "photo"
            else VIDEO_FOOTPRINT_REL_TOLERANCE
        )
        footprint_metric = _record_metric(
            metric_rows, tier=tier, capture_id=loaded["capture_id"], room_id="property",
            metric="whole_property_footprint_m2", object_id="property",
            ground_truth=float(footprint_gt), prediction=footprint_measurement,
            tolerance=footprint_tolerance, relative=True,
        )
        footprint_pred = footprint_metric["prediction"]
        footprint_interval_coverage = footprint_metric["interval_contains_ground_truth"]
        footprint_error = footprint_metric["relative_error"]
        footprint_pass = footprint_metric["gate_pass"] is True
        if tier == "video":
            video_footprint_rows.append({
                "capture_id": loaded["capture_id"],
                "footprint_ground_truth_m2": float(footprint_gt),
                "footprint_prediction_m2": footprint_pred,
                "footprint_relative_error": footprint_error,
                "footprint_tolerance": footprint_tolerance,
                "footprint_pass": footprint_pass,
                "footprint_interval_contains_ground_truth": footprint_interval_coverage,
                "stitched_plan_status": stitched.get("status", "unavailable"),
            })
            continue

        room_map = {str(k): str(v) for k, v in loaded["run"].get("room_matches", {}).items()}
        expected_adjacency = {
            tuple(sorted((str(edge["room_a"]), str(edge["room_b"]))))
            for edge in property_truth.get("adjacency", [])
        }
        reverse = {predicted: truth for truth, predicted in room_map.items()}
        actual_adjacency = {
            tuple(sorted((reverse.get(str(edge["room_a"]), str(edge["room_a"])),
                          reverse.get(str(edge["room_b"]), str(edge["room_b"])))))
            for edge in stitched.get("adjacency", [])
        }
        adjacency_pass = actual_adjacency == expected_adjacency
        no_overlaps = not stitched.get("overlaps", [])
        property_rows.append({
            "capture_id": loaded["capture_id"],
            "footprint_ground_truth_m2": footprint_gt,
            "footprint_prediction_m2": footprint_pred,
            "footprint_relative_error": footprint_error,
            "footprint_tolerance": PHOTO_FOOTPRINT_REL_TOLERANCE,
            "footprint_pass": footprint_pass,
            "footprint_interval_contains_ground_truth": footprint_interval_coverage,
            "adjacency_exact_match": adjacency_pass,
            "overlaps_empty": no_overlaps,
            "stitched_plan_status": stitched.get("status", "unavailable"),
            "gate_pass": footprint_pass and footprint_interval_coverage is True and adjacency_pass and no_overlaps and stitched.get("status") == "complete",
        })

    gates = {}
    for tier, counts in opening_totals.items():
        denominator = counts["ground_truth"] + counts["phantoms"]
        rate = counts["within_tolerance"] / denominator if denominator else None
        gates[f"{tier}_opening_detection_and_width"] = {
            "within_2cm": counts["within_tolerance"], "ground_truth_openings": counts["ground_truth"],
            "phantom_predictions": counts["phantoms"], "score": rate,
            "required_rate": OPENING_REQUIRED_RATE,
            "gate_pass": rate >= OPENING_REQUIRED_RATE if rate is not None else None,
        }
    ceiling_rows = [row for row in metric_rows if row["metric"] == "ceiling_height_m"]
    for tier in {row["tier"] for row in ceiling_rows}:
        tier_rows = [row for row in ceiling_rows if row["tier"] == tier]
        gates[f"{tier}_ceiling_height"] = {
            "within_1_5cm": sum(row["gate_pass"] is True for row in tier_rows),
            "rooms_scored": len(tier_rows),
            "gate_pass": all(row["gate_pass"] is True for row in tier_rows) if tier_rows else None,
        }
    for tier, tolerance in (("photo", PHOTO_WALL_REL_TOLERANCE), ("video", VIDEO_WALL_REL_TOLERANCE)):
        wall_rows = [row for row in metric_rows if row["metric"] == "wall_length_m" and row["tier"] == tier]
        gates[f"{tier}_wall_lengths"] = {
            "within_tolerance": sum(row["gate_pass"] is True for row in wall_rows),
            "walls_scored": len(wall_rows), "relative_tolerance": tolerance,
            "gate_pass": all(row["gate_pass"] is True for row in wall_rows) if wall_rows else None,
        }
    for tier in {item["tier"] for item in repeatability}:
        tier_items = [item for item in repeatability if item["tier"] == tier]
        gates[f"{tier}_repeatability"] = {
            "items_scored": len(tier_items),
            "gate_pass": bool(tier_items) and all(item["gate_pass"] for item in tier_items),
        }
    if property_rows:
        gates["photo_whole_property_stitch"] = {
            "captures_scored": len(property_rows),
            "gate_pass": all(row["gate_pass"] for row in property_rows),
        }
    if video_footprint_rows:
        gates["video_whole_property_footprint"] = {
            "captures_scored": len(video_footprint_rows),
            "within_3_percent": sum(row["footprint_pass"] for row in video_footprint_rows),
            "relative_tolerance": VIDEO_FOOTPRINT_REL_TOLERANCE,
            "gate_pass": all(row["footprint_pass"] for row in video_footprint_rows),
        }

    calibration = defaultdict(lambda: defaultdict(lambda: {"covered": [], "missing_interval": 0, "samples": 0}))
    for row in metric_rows:
        metric_calibration = calibration[row["tier"]][row["metric"]]
        metric_calibration["samples"] += 1
        if row["interval_contains_ground_truth"] is None:
            metric_calibration["missing_interval"] += 1
        else:
            metric_calibration["covered"].append(row["interval_contains_ground_truth"])
    calibration_summary = {
        tier: {
            metric: {
                "samples": summary["samples"],
                "samples_with_interval": len(summary["covered"]),
                "missing_interval": summary["missing_interval"],
                "empirical_coverage": (
                    sum(summary["covered"]) / len(summary["covered"])
                    if summary["covered"] else None
                ),
            }
            for metric, summary in metrics.items()
        }
        for tier, metrics in calibration.items()
    }
    footprint_interval_values = [
        row["footprint_interval_contains_ground_truth"]
        for row in property_rows
        if row["footprint_interval_contains_ground_truth"] is not None
    ]
    if property_rows:
        calibration_summary.setdefault("photo", {})["stitched_footprint_m2"] = {
            "samples": len(property_rows),
            "samples_with_interval": len(footprint_interval_values),
            "missing_interval": len(property_rows) - len(footprint_interval_values),
            "empirical_coverage": (
                sum(footprint_interval_values) / len(footprint_interval_values)
                if footprint_interval_values else None
            ),
        }
    video_footprint_interval_values = [
        row["footprint_interval_contains_ground_truth"]
        for row in video_footprint_rows
        if row["footprint_interval_contains_ground_truth"] is not None
    ]
    if video_footprint_rows:
        calibration_summary.setdefault("video", {})["whole_property_footprint_m2"] = {
            "samples": len(video_footprint_rows),
            "samples_with_interval": len(video_footprint_interval_values),
            "missing_interval": len(video_footprint_rows) - len(video_footprint_interval_values),
            "empirical_coverage": (
                sum(video_footprint_interval_values) / len(video_footprint_interval_values)
                if video_footprint_interval_values else None
            ),
        }
    return {
        "benchmark_id": manifest.get("benchmark_id", manifest_path.stem),
        "benchmark_readiness": _benchmark_readiness(manifest),
        "metric_rows": metric_rows,
        "diagnostic_boundary_candidate_area_rows": candidate_area_rows,
        "diagnostic_boundary_candidate_wall_rows": candidate_wall_rows,
        "repeatability": repeatability,
        "photo_property_stitch": property_rows,
        "video_property_footprint": video_footprint_rows,
        "gates": gates,
        "interval_calibration": calibration_summary,
        "limitations": [
            "Only explicitly mapped ground-truth objects are compared; reviewer mapping quality matters.",
            "Missing or unavailable product measurements fail applicable gates and remain visible in metric_rows.",
            "Interval coverage is empirical and cannot establish calibration with a small sample set.",
            "Timing, drift ablation, and incumbent comparison require separate evidence and are not inferred here.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Score Property Vision result.json files against benchmark ground truth.")
    parser.add_argument("manifest", type=Path, help="Benchmark manifest JSON; see benchmark/ground_truth.template.json")
    parser.add_argument("--output", type=Path, help="Report path (default: benchmark_report.json beside the manifest)")
    args = parser.parse_args()
    report = evaluate(args.manifest)
    output = args.output or args.manifest.resolve().parent / "benchmark_report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Benchmark report: {output}")
    readiness = report["benchmark_readiness"]
    print(f"Benchmark readiness: {'READY' if readiness['ready'] else 'INCOMPLETE'}")
    for name, check in readiness["checks"].items():
        print(f"readiness/{name}: {'PASS' if check['passed'] else 'INCOMPLETE'}")
    for name, gate in report["gates"].items():
        state = gate.get("gate_pass")
        print(f"{name}: {'PASS' if state is True else 'FAIL' if state is False else 'NOT SCORED'}")


if __name__ == "__main__":
    main()
