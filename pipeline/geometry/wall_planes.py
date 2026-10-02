"""Provisional vertical-plane candidates from a metric RGB-D point cloud.

The candidates are diagnostics only. A planar patch or a hole in its sampled
returns is not, by itself, a room wall or a door/window.
"""

from pathlib import Path

import cv2
import numpy as np


def analyze_wall_planes(
    points: np.ndarray,
    output_dir: Path,
    *,
    vertical_axis: str,
    provisional_floor_level_m: float,
    floor_coverage_outline_xy: list[list[float]] | None = None,
    random_seed: int = 7,
) -> dict:
    points = np.asarray(points, dtype=np.float32)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) < 100:
        raise ValueError("Wall analysis requires at least 100 points in an N x 3 array.")
    if vertical_axis not in "xyz":
        raise ValueError("vertical_axis must be x, y, or z.")

    v_axis = "xyz".index(vertical_axis)
    h_axes = [axis for axis in range(3) if axis != v_axis]
    floor = float(provisional_floor_level_m)
    vertical = points[:, v_axis]
    # The floor analysis assumes the positive vertical direction points up.
    # Keep the crop conservative and explicitly report that assumption.
    mask = (vertical >= floor + 0.15) & (vertical <= floor + 3.5)
    candidates = points[mask]
    if len(candidates) < 100:
        raise ValueError("Too few points above the provisional floor for wall analysis.")

    # Voxel thinning limits RANSAC cost and reduces dense near-field weighting.
    voxel = 0.04
    keys = np.floor(candidates / voxel).astype(np.int32)
    _, unique_indices = np.unique(keys, axis=0, return_index=True)
    cloud = candidates[np.sort(unique_indices)]
    if len(cloud) > 60_000:
        sample_indices = np.linspace(0, len(cloud) - 1, 60_000, dtype=np.int64)
        cloud = cloud[sample_indices]

    rng = np.random.default_rng(random_seed)
    residual = np.ones(len(cloud), dtype=bool)
    planes = []
    distance_threshold = 0.04
    min_inliers = max(120, int(len(cloud) * 0.012))
    for _ in range(8):
        indices = np.flatnonzero(residual)
        if len(indices) < min_inliers:
            break
        best = None
        for _ in range(500):
            triplet = cloud[rng.choice(indices, size=3, replace=False)]
            normal = np.cross(triplet[1] - triplet[0], triplet[2] - triplet[0])
            norm = float(np.linalg.norm(normal))
            if norm < 1e-7:
                continue
            normal /= norm
            # A wall normal is approximately horizontal (perpendicular to up).
            if abs(float(normal[v_axis])) > 0.20:
                continue
            offset = -float(np.dot(normal, triplet[0]))
            distances = np.abs(cloud[indices] @ normal + offset)
            inlier_local = distances <= distance_threshold
            count = int(inlier_local.sum())
            if best is None or count > best[0]:
                best = (count, normal.copy(), offset, indices[inlier_local])
        if best is None or best[0] < min_inliers:
            break

        _, normal, _, inlier_indices = best
        patch = cloud[inlier_indices]
        # Refit the plane using PCA, then recompute its inliers against all points.
        centroid = patch.mean(axis=0)
        _, _, vh = np.linalg.svd(patch - centroid, full_matrices=False)
        normal = vh[-1]
        if abs(float(normal[v_axis])) > 0.20:
            residual[inlier_indices] = False
            continue
        distances = np.abs((cloud - centroid) @ normal)
        inlier_indices = np.flatnonzero(residual & (distances <= distance_threshold))
        if len(inlier_indices) < min_inliers:
            break
        patch = cloud[inlier_indices]
        centroid = patch.mean(axis=0)
        # Horizontal direction lying in the wall plane.
        tangent = np.zeros(3, dtype=np.float32)
        tangent[h_axes] = (-normal[h_axes[1]], normal[h_axes[0]])
        tangent_norm = float(np.linalg.norm(tangent))
        if tangent_norm < 1e-6:
            residual[inlier_indices] = False
            continue
        tangent /= tangent_norm
        along = patch @ tangent
        height = patch[:, v_axis]
        length_m = float(np.percentile(along, 98) - np.percentile(along, 2))
        height_low, height_high = np.percentile(height, [2, 98])
        height_m = float(height_high - height_low)
        horizontal_normal = normal[h_axes].astype(np.float64)
        horizontal_normal /= max(float(np.linalg.norm(horizontal_normal)), 1e-8)
        horizontal_tangent = np.array([-horizontal_normal[1], horizontal_normal[0]])
        horizontal_patch = patch[:, h_axes].astype(np.float64)
        along_horizontal = horizontal_patch @ horizontal_tangent
        along_lo, along_hi = np.percentile(along_horizontal, [2, 98])
        normal_coordinate = float(np.median(horizontal_patch @ horizontal_normal))
        endpoint_a = horizontal_normal * normal_coordinate + horizontal_tangent * along_lo
        endpoint_b = horizontal_normal * normal_coordinate + horizontal_tangent * along_hi
        horizontal_offset = -normal_coordinate
        planes.append({
            "normal": [round(float(value), 5) for value in normal],
            "offset_m": round(float(-np.dot(normal, centroid)), 5),
            "horizontal_normal": [round(float(value), 6) for value in horizontal_normal],
            "horizontal_offset_m": round(horizontal_offset, 5),
            "projected_endpoints_m": [
                [round(float(value), 4) for value in endpoint_a],
                [round(float(value), 4) for value in endpoint_b],
            ],
            "along_interval_m": [round(float(along_lo), 4), round(float(along_hi), 4)],
            "point_count": int(len(patch)),
            "observed_length_m": round(length_m, 3),
            "observed_height_m": round(height_m, 3),
            "vertical_support_range_above_floor_m": [
                round(float(height_low - floor), 3), round(float(height_high - floor), 3)
            ],
            "observed_patch_area_m2": round(length_m * height_m, 3),
            "fit_inlier_fraction": round(len(patch) / max(1, len(cloud)), 4),
            "candidate_gaps": _find_candidate_gaps(patch, tangent, v_axis, floor),
        })
        residual[inlier_indices] = False

    planes.sort(key=lambda plane: plane["point_count"], reverse=True)
    planes = _deduplicate_overlapping_planes(planes)
    for index, plane in enumerate(planes):
        plane["candidate_id"] = f"wall_candidate_{index + 1}"
    boundaries = _find_closed_boundary_hypotheses(planes)
    floor_outline = np.asarray(floor_coverage_outline_xy or [], dtype=np.float64)
    boundary_alignment = _align_wall_spans_to_floor_outline(planes, floor_outline)
    aligned_candidate_ids = {
        item["candidate_id"] for item in boundary_alignment.get("wall_candidates", [])
        if item.get("status") == "aligned_boundary_candidate"
    }
    intersection_cycles = _find_intersection_cycle_hypotheses(
        planes, aligned_candidate_ids, floor_outline
    )
    boundaries["line_intersection_hypotheses"] = intersection_cycles
    opening_analysis = _analyze_opening_candidates(planes, boundaries)
    preview_path = Path(output_dir) / "wall_plane_candidates.png"
    _write_preview(cloud, planes, v_axis, h_axes, preview_path)
    boundary_preview_path = Path(output_dir) / "wall_boundary_diagnostic.png"
    _write_boundary_preview(planes, boundaries, floor_outline, boundary_alignment, boundary_preview_path)
    return {
        "status": "diagnostic_only",
        "vertical_axis": vertical_axis,
        "floor_level_source": "Provisional floor-return estimate; positive axis direction assumed upward.",
        "input_point_count": int(len(points)),
        "points_in_height_band": int(mask.sum()),
        "voxel_resolution_m": voxel,
        "ransac_distance_threshold_m": distance_threshold,
        "candidate_count": len(planes),
        "deduplication": {
            "method": "Suppress near-coplanar detections with overlapping projected wall spans.",
            "normal_angle_threshold_degrees": 4,
            "plane_separation_threshold_m": 0.20,
            "minimum_overlap_fraction": 0.5,
            "candidate_count_before_deduplication": int(sum(p["merged_detection_count"] for p in planes)),
            "candidate_count_after_deduplication": len(planes),
        },
        "wall_plane_candidates": planes,
        "room_boundary_hypotheses": boundaries,
        "floor_coverage_alignment": boundary_alignment,
        "opening_analysis": opening_analysis,
        "preview": preview_path.name,
        "boundary_preview": boundary_preview_path.name,
        "limitations": [
            "Plane lengths, heights, and patch areas describe sampled planar support, not verified room dimensions or complete surface areas.",
            "Candidate extent values are uncalibrated diagnostics and do not have validated confidence intervals.",
            "Candidate gaps are missing-return regions and may result from occlusion, sparse sampling, or reconstruction error; they are not classified openings.",
            "Gravity orientation, depth scale, camera registration, and pose accuracy remain unvalidated against ground truth.",
            "Closed endpoint cycles are boundary hypotheses only; they are not semantic room segmentation, adjacency, opening dimensions, or an accepted rendered floor plan.",
        ],
    }


def _align_wall_spans_to_floor_outline(planes: list[dict], outline: np.ndarray) -> dict:
    """Compare wall spans to floor-return boundary evidence using provisional thresholds."""
    if outline.ndim != 2 or outline.shape[1:] != (2,) or len(outline) < 4:
        return {
            "status": "unavailable",
            "method": "Wall endpoint-to-floor-outline support comparison.",
            "aligned_candidate_count": 0,
            "candidate_count": len(planes),
            "wall_candidates": [],
            "limitations": ["A valid floor-coverage outline was not available for comparison."],
        }

    results = []
    for plane in planes:
        endpoints = np.asarray(plane.get("projected_endpoints_m", []), dtype=np.float64)
        if endpoints.shape != (2, 2):
            continue
        direction = endpoints[1] - endpoints[0]
        length = float(np.linalg.norm(direction))
        if length < 1e-6:
            continue
        tangent = direction / length
        normal = np.array([-tangent[1], tangent[0]])
        relative = outline - endpoints[0]
        along = relative @ tangent
        perpendicular = np.abs(relative @ normal)
        in_segment = (along >= -0.15) & (along <= length + 0.15)
        support = in_segment & (perpendicular <= 0.20)
        support_points = outline[support]
        if len(support_points) >= 2:
            support_along = (support_points - endpoints[0]) @ tangent
            coverage = max(0.0, min(length, float(support_along.max())) - max(0.0, float(support_along.min()))) / length
            offset = float(np.median(np.abs((support_points - endpoints[0]) @ normal)))
        else:
            coverage = 0.0
            offset = None

        if len(support_points) >= 3:
            centered = support_points - support_points.mean(axis=0)
            _, eigenvectors = np.linalg.eigh(centered.T @ centered)
            principal = eigenvectors[:, -1]
            angle = float(np.degrees(np.arccos(np.clip(abs(float(np.dot(principal, tangent))), -1.0, 1.0))))
        else:
            angle = None

        aligned = (
            len(support_points) >= 4
            and offset is not None and offset <= 0.15
            and angle is not None and angle <= 15.0
            and coverage >= 0.25
        )
        results.append({
            "candidate_id": plane.get("candidate_id"),
            "status": "aligned_boundary_candidate" if aligned else "weak_or_unmatched",
            "outline_support_point_count": int(len(support_points)),
            "outline_coverage_ratio": round(float(coverage), 3),
            "median_perpendicular_offset_m": round(offset, 3) if offset is not None else None,
            "principal_direction_difference_degrees": round(angle, 2) if angle is not None else None,
            "thresholds": {
                "maximum_support_offset_m": 0.15,
                "maximum_direction_difference_degrees": 15.0,
                "minimum_outline_coverage_ratio": 0.25,
                "minimum_support_points": 4,
            },
        })

    return {
        "status": "diagnostic_only",
        "method": "Compare each fitted wall span with nearby points on the observed floor-coverage outline.",
        "aligned_candidate_count": sum(item["status"] == "aligned_boundary_candidate" for item in results),
        "candidate_count": len(results),
        "wall_candidates": results,
        "limitations": [
            "Floor-return coverage can stop at furniture, occlusion, or incomplete scanning and is not a room footprint.",
            "Alignment thresholds are provisional geometry filters and have not been calibrated or validated against ground truth.",
            "An aligned candidate is not a semantic wall, room boundary, or measured surface.",
        ],
    }


def _find_intersection_cycle_hypotheses(
    planes: list[dict], aligned_candidate_ids: set[str], outline: np.ndarray,
) -> dict:
    """Split aligned wall spans at intersections and enumerate small planar faces."""
    selected = [
        plane for plane in planes
        if plane.get("candidate_id") in aligned_candidate_ids
        and len(plane.get("projected_endpoints_m", [])) == 2
    ]
    if len(selected) < 3:
        return {
            "status": "insufficient_candidates",
            "method": "Planar faces from intersections of coverage-aligned wall spans.",
            "candidate_count": 0,
            "hypotheses": [],
        }

    split_points = []
    for plane in selected:
        endpoints = np.asarray(plane["projected_endpoints_m"], dtype=np.float64)
        split_points.append([(0.0, endpoints[0]), (1.0, endpoints[1])])

    def cross(a: np.ndarray, b: np.ndarray) -> float:
        return float(a[0] * b[1] - a[1] * b[0])

    for i in range(len(selected)):
        a, b = (np.asarray(point, dtype=np.float64) for point in selected[i]["projected_endpoints_m"])
        r = b - a
        for j in range(i + 1, len(selected)):
            c, d = (np.asarray(point, dtype=np.float64) for point in selected[j]["projected_endpoints_m"])
            s = d - c
            denominator = cross(r, s)
            if abs(denominator) < 1e-7:
                continue
            delta = c - a
            t = cross(delta, s) / denominator
            u = cross(delta, r) / denominator
            if -1e-6 <= t <= 1.0 + 1e-6 and -1e-6 <= u <= 1.0 + 1e-6:
                point = a + np.clip(t, 0.0, 1.0) * r
                split_points[i].append((float(np.clip(t, 0.0, 1.0)), point))
                split_points[j].append((float(np.clip(u, 0.0, 1.0)), point))

    nodes: list[np.ndarray] = []
    segment_nodes: list[list[tuple[float, int]]] = []
    snap_tolerance_m = 0.25
    for points_on_segment in split_points:
        assigned = []
        for along, point in sorted(points_on_segment, key=lambda item: item[0]):
            if nodes:
                distances = [float(np.linalg.norm(point - node)) for node in nodes]
                nearest = int(np.argmin(distances))
                if distances[nearest] <= snap_tolerance_m:
                    node_id = nearest
                else:
                    node_id = len(nodes)
                    nodes.append(point.copy())
            else:
                node_id = 0
                nodes.append(point.copy())
            if not assigned or assigned[-1][1] != node_id:
                assigned.append((along, node_id))
        segment_nodes.append(assigned)

    edge_support: dict[tuple[int, int], set[str]] = {}
    for plane, assignments in zip(selected, segment_nodes):
        for (_, node_a), (_, node_b) in zip(assignments, assignments[1:]):
            if node_a == node_b or np.linalg.norm(nodes[node_a] - nodes[node_b]) < 0.25:
                continue
            edge = tuple(sorted((node_a, node_b)))
            edge_support.setdefault(edge, set()).add(str(plane["candidate_id"]))
    if len(edge_support) < 3:
        return {
            "status": "no_intersection_cycles",
            "method": "Planar faces from intersections of coverage-aligned wall spans.",
            "candidate_count": 0,
            "hypotheses": [],
        }

    adjacency: dict[int, list[int]] = {}
    for node_a, node_b in edge_support:
        adjacency.setdefault(node_a, []).append(node_b)
        adjacency.setdefault(node_b, []).append(node_a)
    for node, neighbors in adjacency.items():
        neighbors.sort(key=lambda other: float(np.arctan2(
            nodes[other][1] - nodes[node][1], nodes[other][0] - nodes[node][0]
        )))

    visited: set[tuple[int, int]] = set()
    canonical_cycles: set[tuple[int, ...]] = set()
    hypotheses = []
    selected_by_id = {str(plane["candidate_id"]): plane for plane in selected}
    for start_a, neighbors in adjacency.items():
        for start_b in neighbors:
            start_edge = (start_a, start_b)
            if start_edge in visited:
                continue
            edge = start_edge
            face_nodes = []
            local_edges: set[tuple[int, int]] = set()
            closed = False
            for _ in range(max(20, len(edge_support) * 2 + 2)):
                if edge in local_edges:
                    break
                local_edges.add(edge)
                node_a, node_b = edge
                face_nodes.append(node_a)
                neighbors_at_b = adjacency[node_b]
                reverse_index = neighbors_at_b.index(node_a)
                next_node = neighbors_at_b[(reverse_index - 1) % len(neighbors_at_b)]
                edge = (node_b, next_node)
                if edge == start_edge:
                    closed = True
                    break
            visited.update(local_edges)
            if not closed or len(face_nodes) < 3 or len(face_nodes) > 12:
                continue

            rotations = [tuple(face_nodes[k:] + face_nodes[:k]) for k in range(len(face_nodes))]
            reversed_nodes = list(reversed(face_nodes))
            rotations.extend(tuple(reversed_nodes[k:] + reversed_nodes[:k]) for k in range(len(reversed_nodes)))
            canonical = min(rotations)
            if canonical in canonical_cycles:
                continue
            canonical_cycles.add(canonical)

            polygon = np.asarray([nodes[node_id] for node_id in face_nodes], dtype=np.float64)
            area = abs(float(np.dot(polygon[:, 0], np.roll(polygon[:, 1], -1)) -
                                  np.dot(polygon[:, 1], np.roll(polygon[:, 0], -1)))) / 2.0
            if not 0.50 <= area <= 60.0:
                continue
            center = polygon.mean(axis=0)
            if len(outline) >= 4 and cv2.pointPolygonTest(
                outline.astype(np.float32), tuple(center.astype(float)), False
            ) < 0:
                continue
            support_ids = set()
            edges = []
            for node_a, node_b in zip(face_nodes, face_nodes[1:] + face_nodes[:1]):
                side_support_ids = sorted(edge_support.get(tuple(sorted((node_a, node_b))), set()))
                support_ids.update(side_support_ids)
                point_a, point_b = nodes[node_a], nodes[node_b]
                side_length = float(np.linalg.norm(point_b - point_a))
                edges.append({
                    "side_id": f"side_{len(edges) + 1}",
                    "vertices_xy_m": [
                        [round(float(point_a[0]), 3), round(float(point_a[1]), 3)],
                        [round(float(point_b[0]), 3), round(float(point_b[1]), 3)],
                    ],
                    "length_m": round(side_length, 3),
                    "supporting_wall_candidates": [
                        {
                            "candidate_id": candidate_id,
                            "observed_length_m": selected_by_id[candidate_id].get("observed_length_m"),
                            "support_point_count": selected_by_id[candidate_id].get("point_count"),
                            "fit_inlier_fraction": selected_by_id[candidate_id].get("fit_inlier_fraction"),
                        }
                        for candidate_id in side_support_ids
                    ],
                    "measurement_uncertainty": {
                        "status": "uncalibrated",
                        "confidence_interval_m": None,
                        "reason": "No independent ground truth or calibrated error model is available.",
                    },
                })

            interior_angles = []
            for index, current in enumerate(polygon):
                previous = polygon[index - 1] - current
                following = polygon[(index + 1) % len(polygon)] - current
                denominator = float(np.linalg.norm(previous) * np.linalg.norm(following))
                if denominator > 1e-8:
                    cosine = float(np.clip(np.dot(previous, following) / denominator, -1.0, 1.0))
                    interior_angles.append(round(float(np.degrees(np.arccos(cosine))), 2))

            all_sides_supported = all(edge["supporting_wall_candidates"] for edge in edges)
            simple = _is_simple_polygon(polygon)
            plausible_shape = (
                simple and 3 <= len(edges) <= 10 and all_sides_supported
                and all(edge["length_m"] >= 0.30 for edge in edges)
                and all(30.0 <= angle <= 150.0 for angle in interior_angles)
                and 0.50 <= area <= 60.0
            )
            area_measurement = {
                "value_m2": round(area, 3),
                "measurement_status": "uncalibrated_candidate_geometry",
                "confidence_interval_m2": None,
                "uncertainty_reason": "No independent ground truth or calibrated error model is available.",
            }
            hypotheses.append({
                "hypothesis_id": f"intersection_cycle_{len(hypotheses) + 1}",
                "status": "diagnostic_only",
                "area_m2": round(area, 3),
                "vertices_xy_m": [[round(float(x), 3), round(float(y), 3)] for x, y in polygon],
                "supporting_wall_candidate_ids": sorted(support_ids),
                "edges": edges,
                "interior_angles_degrees": interior_angles,
                "shape_review": {
                    "status": "plausible_candidate_shape" if plausible_shape else "review_required",
                    "simple_polygon": simple,
                    "all_edges_have_wall_support": all_sides_supported,
                    "side_count": len(edges),
                    "minimum_side_length_m": round(min(edge["length_m"] for edge in edges), 3) if edges else None,
                    "maximum_side_length_m": round(max(edge["length_m"] for edge in edges), 3) if edges else None,
                    "minimum_interior_angle_degrees": min(interior_angles) if interior_angles else None,
                    "maximum_interior_angle_degrees": max(interior_angles) if interior_angles else None,
                    "criteria": "simple polygon; 3-10 supported sides; sides >=0.30 m; angles 30-150 degrees; area 0.50-60 m^2",
                    "limitations": [
                        "A plausible polygon shape does not establish that the face corresponds to a real room.",
                        "The checks are provisional engineering filters, not empirically validated room classification.",
                    ],
                },
                "provisional_area_measurement": area_measurement,
            })

    hypotheses.sort(key=lambda item: item["area_m2"], reverse=True)
    hypotheses = hypotheses[:20]
    return {
        "status": "diagnostic_only" if hypotheses else "no_intersection_cycles",
        "method": "Split coverage-aligned wall spans at 2D intersections; enumerate bounded planar faces inside observed coverage.",
        "candidate_count": len(hypotheses),
        "snap_tolerance_m": snap_tolerance_m,
        "minimum_candidate_area_m2": 0.50,
        "maximum_candidate_area_m2": 60.0,
        "hypotheses": hypotheses,
        "limitations": [
            "Intersections can be caused by pose drift or false wall fits; a closed face does not prove a room boundary.",
            "Small openings, occluded wall runs, and disconnected or multi-room geometry are not resolved by this method.",
            "Candidate areas and thresholds are uncalibrated and require comparison with labeled geometry.",
        ],
    }


def _analyze_opening_candidates(planes: list[dict], boundaries: dict) -> dict:
    """Classify geometric voids as opening candidates without asserting semantics."""
    plane_by_id = {str(plane.get("candidate_id")): plane for plane in planes}
    surface_voids = []
    for plane in planes:
        for index, gap in enumerate(plane.get("candidate_gaps", []), start=1):
            width = float(gap.get("width_extent_m", 0.0))
            height = float(gap.get("height_extent_m", 0.0))
            center_height = float(gap.get("center_height_above_provisional_floor_m", 0.0))
            bottom = center_height - height / 2.0
            if 0.50 <= width <= 1.80 and height >= 1.60 and bottom <= 0.25:
                candidate_class = "possible_doorway"
            elif 0.30 <= width <= 2.50 and 0.35 <= height <= 2.20 and bottom >= 0.45:
                candidate_class = "possible_window_or_wall_void"
            else:
                candidate_class = "unclassified_wall_void"
            surface_voids.append({
                "candidate_id": f"{plane.get('candidate_id')}_void_{index}",
                "wall_candidate_id": plane.get("candidate_id"),
                "candidate_class": candidate_class,
                "status": "unverified_geometry_candidate",
                "width_extent_m": round(width, 3),
                "height_extent_m": round(height, 3),
                "bottom_above_provisional_floor_m": round(bottom, 3),
                "center_along_wall_m": gap.get("center_along_wall_m"),
                "occupied_grid_cells": gap.get("occupied_grid_cells"),
                "measurement_uncertainty": {
                    "status": "uncalibrated",
                    "width_confidence_interval_m": None,
                    "height_confidence_interval_m": None,
                },
            })

    endpoint_reviews = []
    for index, gap in enumerate(boundaries.get("nearby_unclosed_endpoint_gaps", []), start=1):
        plane_a = plane_by_id.get(str(gap.get("candidate_a")))
        plane_b = plane_by_id.get(str(gap.get("candidate_b")))
        result = {
            "candidate_id": f"boundary_gap_{index}",
            "candidate_a": gap.get("candidate_a"),
            "candidate_b": gap.get("candidate_b"),
            "gap_extent_m": gap.get("gap_extent_m"),
            "status": "unclassified_boundary_discontinuity",
            "candidate_class": "unclassified_open_boundary_gap",
        }
        if plane_a and plane_b:
            segment_a = np.asarray(plane_a.get("projected_endpoints_m", []), dtype=np.float64)
            segment_b = np.asarray(plane_b.get("projected_endpoints_m", []), dtype=np.float64)
            if segment_a.shape == (2, 2) and segment_b.shape == (2, 2):
                tangent_a = segment_a[1] - segment_a[0]
                tangent_b = segment_b[1] - segment_b[0]
                tangent_a /= max(float(np.linalg.norm(tangent_a)), 1e-8)
                tangent_b /= max(float(np.linalg.norm(tangent_b)), 1e-8)
                angle = float(np.degrees(np.arccos(np.clip(abs(float(np.dot(tangent_a, tangent_b))), -1.0, 1.0))))
                point_a = np.asarray(gap.get("endpoint_a_xy_m"), dtype=np.float64)
                point_b = np.asarray(gap.get("endpoint_b_xy_m"), dtype=np.float64)
                gap_vector = point_b - point_a
                lateral_offset = abs(float(tangent_a[0] * gap_vector[1] - tangent_a[1] * gap_vector[0]))
                result["direction_difference_degrees"] = round(angle, 2)
                result["lateral_offset_m"] = round(lateral_offset, 3)
                if angle <= 15.0 and lateral_offset <= 0.20 and 0.50 <= float(gap.get("gap_extent_m", 0.0)) <= 1.80:
                    result["status"] = "possible_opening_or_unobserved_wall_segment"
                    result["candidate_class"] = "possible_doorway_or_wall_gap"
                else:
                    result["review_reason"] = "Adjacent spans do not satisfy direction and shared-line checks for an opening interpretation."
        endpoint_reviews.append(result)

    possible_surface_openings = [
        item for item in surface_voids
        if item["candidate_class"] in {"possible_doorway", "possible_window_or_wall_void"}
    ]
    possible_boundary_openings = [
        item for item in endpoint_reviews
        if item["status"] == "possible_opening_or_unobserved_wall_segment"
    ]
    return {
        "status": "diagnostic_only",
        "candidate_count": len(possible_surface_openings) + len(possible_boundary_openings),
        "surface_void_candidates": surface_voids,
        "boundary_gap_reviews": endpoint_reviews,
        "opening_candidates": possible_surface_openings + possible_boundary_openings,
        "classification_policy": {
            "doorway_hint": "0.50-1.80 m width, >=1.60 m vertical void, bottom <=0.25 m above provisional floor",
            "window_hint": "0.30-2.50 m width, 0.35-2.20 m height, bottom >=0.45 m above provisional floor",
            "boundary_gap_hint": "0.50-1.80 m gap between near-collinear wall spans with <=0.20 m lateral offset",
            "semantic_status": "All labels are unverified candidates; no door or window is asserted.",
        },
        "limitations": [
            "Missing returns can be caused by occlusion, sparse sampling, pose error, or incomplete wall support.",
            "A gap between wall-span endpoints is not sufficient evidence of an opening unless the spans are collinear and vertical coverage supports it.",
            "Candidate extents and classification thresholds are uncalibrated and have no validated confidence intervals.",
        ],
    }


def _is_simple_polygon(polygon: np.ndarray) -> bool:
    """Return false when non-adjacent polygon edges cross or overlap."""
    def orientation(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
        return float((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))

    count = len(polygon)
    for i in range(count):
        a, b = polygon[i], polygon[(i + 1) % count]
        for j in range(i + 1, count):
            if j == i or j == (i + 1) % count or i == (j + 1) % count:
                continue
            c, d = polygon[j], polygon[(j + 1) % count]
            o1, o2 = orientation(a, b, c), orientation(a, b, d)
            o3, o4 = orientation(c, d, a), orientation(c, d, b)
            if o1 * o2 < -1e-8 and o3 * o4 < -1e-8:
                return False
    return True


def _write_boundary_preview(
    planes: list[dict], boundaries: dict, floor_outline: np.ndarray,
    alignment: dict, path: Path,
) -> None:
    """Render a top-down diagnostic of floor coverage, candidate spans, and gaps."""
    canvas = np.full((900, 1200, 3), 250, dtype=np.uint8)
    segments = [
        np.asarray(plane["projected_endpoints_m"], dtype=np.float64)
        for plane in planes
        if len(plane.get("projected_endpoints_m", [])) == 2
    ]
    if not segments:
        cv2.putText(canvas, "No wall-plane candidates", (50, 80), cv2.FONT_HERSHEY_SIMPLEX,
                    0.9, (30, 30, 30), 2, cv2.LINE_AA)
        cv2.imwrite(str(path), canvas)
        return

    extent_items = [np.concatenate(segments, axis=0)]
    if floor_outline.ndim == 2 and floor_outline.shape[1:] == (2,) and len(floor_outline) >= 3:
        extent_items.append(floor_outline)
    endpoints = np.concatenate(extent_items, axis=0)
    low = endpoints.min(axis=0)
    high = endpoints.max(axis=0)
    span = np.maximum(high - low, 0.5)
    padding = np.maximum(span * 0.08, 0.25)
    low -= padding
    high += padding
    usable_w, usable_h = 1060, 740
    scale = min(usable_w / max(high[0] - low[0], 1e-6),
                usable_h / max(high[1] - low[1], 1e-6))
    origin = np.array([70.0, 820.0])

    def pixel(point: np.ndarray) -> tuple[int, int]:
        relative = (np.asarray(point, dtype=np.float64) - low) * scale
        return int(origin[0] + relative[0]), int(origin[1] - relative[1])

    if floor_outline.ndim == 2 and floor_outline.shape[1:] == (2,) and len(floor_outline) >= 3:
        polygon = np.asarray([pixel(point) for point in floor_outline], dtype=np.int32).reshape(-1, 1, 2)
        cv2.polylines(canvas, [polygon], True, (90, 90, 90), 2, cv2.LINE_AA)
        cv2.putText(canvas, "observed floor coverage", (int(np.min(polygon[:, 0, 0])),
                    max(58, int(np.min(polygon[:, 0, 1])) - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (70, 70, 70), 1, cv2.LINE_AA)

    aligned_ids = {
        item.get("candidate_id") for item in alignment.get("wall_candidates", [])
        if item.get("status") == "aligned_boundary_candidate"
    }

    cv2.putText(canvas, "Wall boundary candidates (diagnostic only)", (40, 38),
                cv2.FONT_HERSHEY_SIMPLEX, 0.85, (35, 35, 35), 2, cv2.LINE_AA)
    for index, plane in enumerate(planes):
        points = plane.get("projected_endpoints_m", [])
        if len(points) != 2:
            continue
        a, b = pixel(np.asarray(points[0])), pixel(np.asarray(points[1]))
        color = (30, 150, 30) if plane.get("candidate_id") in aligned_ids else (180, 110, 20)
        cv2.line(canvas, a, b, color, 3, cv2.LINE_AA)
        cv2.circle(canvas, a, 6, (20, 130, 230), -1, cv2.LINE_AA)
        cv2.circle(canvas, b, 6, (20, 130, 230), -1, cv2.LINE_AA)
        label = plane.get("candidate_id", f"candidate_{index + 1}")
        midpoint = ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2)
        cv2.putText(canvas, label, (midpoint[0] + 6, midpoint[1] - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (30, 30, 30), 1, cv2.LINE_AA)

    for gap in boundaries.get("nearby_unclosed_endpoint_gaps", []):
        a = pixel(np.asarray(gap["endpoint_a_xy_m"]))
        b = pixel(np.asarray(gap["endpoint_b_xy_m"]))
        distance = float(gap.get("gap_extent_m", 0.0))
        direction = np.asarray(b, dtype=np.float64) - np.asarray(a, dtype=np.float64)
        length = float(np.linalg.norm(direction))
        if length > 0:
            direction /= length
            for start in np.arange(0.0, length, 14.0):
                end = min(start + 7.0, length)
                p0 = tuple(np.round(np.asarray(a) + direction * start).astype(int))
                p1 = tuple(np.round(np.asarray(a) + direction * end).astype(int))
                cv2.line(canvas, p0, p1, (40, 40, 220), 2, cv2.LINE_AA)
        mid = ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2)
        cv2.putText(canvas, f"unclosed {distance:.2f} m", (mid[0] + 5, mid[1] - 7),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (40, 40, 220), 1, cv2.LINE_AA)

    for hypothesis in boundaries.get("line_intersection_hypotheses", {}).get("hypotheses", []):
        vertices = hypothesis.get("vertices_xy_m", [])
        if len(vertices) < 3:
            continue
        polygon = np.asarray([pixel(np.asarray(point)) for point in vertices], dtype=np.int32).reshape(-1, 1, 2)
        cv2.polylines(canvas, [polygon], True, (200, 0, 200), 3, cv2.LINE_AA)
        center = tuple(np.round(polygon[:, 0, :].mean(axis=0)).astype(int))
        cv2.putText(canvas, f"face candidate {hypothesis['area_m2']:.2f} m^2",
                    (center[0] + 6, center[1] - 8), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (180, 0, 180), 1, cv2.LINE_AA)

    cv2.putText(canvas, "Orange: endpoints   Blue: unmatched spans   Green: aligned spans   Purple: face candidate   Red: gap",
                (40, 865), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (50, 50, 50), 1, cv2.LINE_AA)
    cv2.imwrite(str(path), canvas)


def _deduplicate_overlapping_planes(planes: list[dict]) -> list[dict]:
    """Collapse repeated detections of the same wall span, preserving support evidence."""
    angle_limit = float(np.cos(np.deg2rad(4.0)))
    separation_limit = 0.20
    minimum_overlap = 0.5
    kept: list[dict] = []
    for candidate in planes:
        duplicate = None
        for existing in kept:
            n1 = np.asarray(candidate["horizontal_normal"], dtype=np.float64)
            n2 = np.asarray(existing["horizontal_normal"], dtype=np.float64)
            d1 = float(candidate["horizontal_offset_m"])
            d2 = float(existing["horizontal_offset_m"])
            if float(np.dot(n1, n2)) < 0:
                n2, d2 = -n2, -d2
            if float(np.dot(n1, n2)) < angle_limit or abs(d1 - d2) > separation_limit:
                continue
            interval_a = candidate["along_interval_m"]
            interval_b = existing["along_interval_m"]
            overlap = max(0.0, min(interval_a[1], interval_b[1]) - max(interval_a[0], interval_b[0]))
            shorter = min(interval_a[1] - interval_a[0], interval_b[1] - interval_b[0])
            if shorter > 0 and overlap / shorter >= minimum_overlap:
                duplicate = existing
                break
        if duplicate is None:
            candidate["merged_detection_count"] = 1
            candidate["merged_support_point_count"] = int(candidate["point_count"])
            kept.append(candidate)
        else:
            duplicate["merged_detection_count"] += 1
            duplicate["merged_support_point_count"] += int(candidate["point_count"])
            # Retain the union extent along the existing line, but do not bridge
            # disjoint segments: candidates are merged only when spans overlap.
            duplicate["along_interval_m"] = [
                round(min(duplicate["along_interval_m"][0], candidate["along_interval_m"][0]), 4),
                round(max(duplicate["along_interval_m"][1], candidate["along_interval_m"][1]), 4),
            ]
            duplicate["observed_length_m"] = round(
                duplicate["along_interval_m"][1] - duplicate["along_interval_m"][0], 3
            )
            duplicate["observed_patch_area_m2"] = round(
                duplicate["observed_length_m"] * duplicate["observed_height_m"], 3
            )
    return kept


def _find_closed_boundary_hypotheses(planes: list[dict], *, snap_tolerance_m: float = 0.30) -> dict:
    """Find small cycles by snapping detected wall endpoints; never labels a room."""
    endpoints = []
    for edge_index, plane in enumerate(planes):
        segment = plane.get("projected_endpoints_m", [])
        if len(segment) != 2:
            continue
        endpoints.append((edge_index, 0, np.asarray(segment[0], dtype=np.float64)))
        endpoints.append((edge_index, 1, np.asarray(segment[1], dtype=np.float64)))

    nodes: list[np.ndarray] = []
    assignments: dict[tuple[int, int], int] = {}
    for edge_index, endpoint_index, point in endpoints:
        choices = [(float(np.linalg.norm(point - node)), node_id) for node_id, node in enumerate(nodes)]
        if choices and min(choices)[0] <= snap_tolerance_m:
            _, node_id = min(choices)
            # Keep a stable node location for deterministic cycle evidence.
        else:
            node_id = len(nodes)
            nodes.append(point.copy())
        assignments[(edge_index, endpoint_index)] = node_id

    graph: dict[int, list[tuple[int, int]]] = {node_id: [] for node_id in range(len(nodes))}
    for edge_index, plane in enumerate(planes):
        a, b = assignments.get((edge_index, 0)), assignments.get((edge_index, 1))
        if a is None or b is None or a == b:
            continue
        graph[a].append((b, edge_index))
        graph[b].append((a, edge_index))

    found: dict[tuple[int, ...], tuple[list[int], list[int]]] = {}
    max_cycle_edges = min(8, len(planes))
    for start in graph:
        def walk(node: int, path_nodes: list[int], path_edges: list[int]) -> None:
            if len(path_edges) >= max_cycle_edges:
                return
            for neighbor, edge_index in graph[node]:
                if path_edges and edge_index == path_edges[-1]:
                    continue
                if neighbor == start and len(path_edges) >= 2:
                    cycle_edges = path_edges + [edge_index]
                    cycle_nodes = path_nodes + [start]
                    canonical_edges = tuple(sorted(cycle_edges))
                    if canonical_edges not in found and len(set(cycle_edges)) == len(cycle_edges):
                        found[canonical_edges] = (cycle_nodes[:-1], cycle_edges)
                elif neighbor not in path_nodes and len(path_edges) < max_cycle_edges - 1:
                    walk(neighbor, path_nodes + [neighbor], path_edges + [edge_index])

        walk(start, [start], [])

    hypotheses = []
    for cycle_nodes, cycle_edges in found.values():
        if len(cycle_nodes) < 3:
            continue
        polygon = np.asarray([nodes[node] for node in cycle_nodes], dtype=np.float64)
        x, y = polygon[:, 0], polygon[:, 1]
        area = 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))
        perimeter = sum(
            float(np.linalg.norm(polygon[(i + 1) % len(polygon)] - polygon[i]))
            for i in range(len(polygon))
        )
        if area < 1.0 or perimeter > 40.0:
            continue
        hypotheses.append({
            "hypothesis_id": f"boundary_hypothesis_{len(hypotheses) + 1}",
            "status": "unverified_closed_wall_endpoint_cycle",
            "wall_candidate_ids": [planes[index]["candidate_id"] for index in cycle_edges],
            "vertices_xy_m": [[round(float(a), 3), round(float(b), 3)] for a, b in polygon],
            "perimeter_extent_m": round(perimeter, 3),
            "enclosed_area_extent_m2": round(area, 3),
            "endpoint_snap_tolerance_m": snap_tolerance_m,
        })
    hypotheses.sort(key=lambda item: item["enclosed_area_extent_m2"])
    open_nodes = [node_id for node_id, neighbors in graph.items() if len(neighbors) == 1]
    nearest_gaps = []
    seen_pairs = set()
    for i, node_a in enumerate(open_nodes):
        for node_b in graph:
            if node_a == node_b or any(neighbor == node_b for neighbor, _ in graph[node_a]):
                continue
            if node_b in open_nodes and open_nodes.index(node_b) < i:
                continue
            distance = float(np.linalg.norm(nodes[node_a] - nodes[node_b]))
            if not snap_tolerance_m < distance <= 1.5:
                continue
            pair = tuple(sorted((node_a, node_b)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            candidate_a = graph[node_a][0][1]
            candidate_b = min(
                graph[node_b],
                key=lambda item: float(np.linalg.norm(nodes[item[0]] - nodes[node_a])),
            )[1]
            nearest_gaps.append({
                "candidate_a": planes[candidate_a]["candidate_id"],
                "endpoint_a_xy_m": [round(float(value), 3) for value in nodes[node_a]],
                "candidate_b": planes[candidate_b]["candidate_id"],
                "endpoint_b_xy_m": [round(float(value), 3) for value in nodes[node_b]],
                "gap_extent_m": round(distance, 3),
                "status": "unverified_open_boundary_gap",
            })
    nearest_gaps.sort(key=lambda item: item["gap_extent_m"])
    return {
        "status": "diagnostic_only",
        "method": "Closed cycles in projected wall-segment endpoints after spatial snapping.",
        "candidate_count": len(hypotheses),
        "hypotheses": hypotheses,
        "open_endpoint_count": len(open_nodes),
        "nearby_unclosed_endpoint_gaps": nearest_gaps[:10],
        "limitations": [
            "An endpoint cycle can enclose several rooms or a partial property boundary and is not assigned a room identity.",
            "Endpoint snapping and extents are uncalibrated; cycles are not measurements with validated confidence intervals.",
            "Nearby open endpoints may be separated by occlusion, a doorway, an omitted wall, or unrelated surfaces; gaps are not classified.",
        ],
    }


def _find_candidate_gaps(patch: np.ndarray, tangent: np.ndarray, vertical_axis: int, floor_level_m: float) -> list[dict]:
    along = patch @ tangent
    height = patch[:, vertical_axis]
    resolution = 0.08
    x0, x1 = float(along.min()), float(along.max())
    y0, y1 = float(height.min()), float(height.max())
    x_edges = np.arange(x0, x1 + resolution, resolution)
    y_edges = np.arange(y0, y1 + resolution, resolution)
    if len(x_edges) < 5 or len(y_edges) < 5:
        return []
    counts, _, _ = np.histogram2d(along, height, bins=(x_edges, y_edges))
    occupied = (counts > 0).astype(np.uint8)
    # Fill only tiny sampling pinholes before locating larger interior voids.
    occupied = cv2.morphologyEx(occupied, cv2.MORPH_CLOSE, np.ones((3, 3), dtype=np.uint8))
    void = (occupied == 0).astype(np.uint8)
    count, labels, stats, centers = cv2.connectedComponentsWithStats(void, connectivity=8)
    gaps = []
    for label in range(1, count):
        x, y, width, height_cells, area = (int(value) for value in stats[label])
        # Exclude gaps touching the patch boundary; they are more likely truncation.
        if x == 0 or y == 0 or x + width >= void.shape[0] or y + height_cells >= void.shape[1]:
            continue
        width_m, height_m = width * resolution, height_cells * resolution
        if area < 8 or width_m < 0.25 or height_m < 0.25 or width_m > 2.5 or height_m > 2.8:
            continue
        gaps.append({
            "candidate_type": "unclassified_missing_return_region",
            "width_extent_m": round(width_m, 2),
            "height_extent_m": round(height_m, 2),
            "center_along_wall_m": round(x0 + float(centers[label][0]) * resolution, 2),
            "center_height_above_provisional_floor_m": round(
                y0 + float(centers[label][1]) * resolution - floor_level_m, 2
            ),
            "occupied_grid_cells": area,
        })
    return gaps[:20]


def _write_preview(cloud: np.ndarray, planes: list[dict], vertical_axis: int, horizontal_axes: list[int], path: Path) -> None:
    # Project full thinned cloud to the provisional horizontal plane. Highlight
    # candidate plane supports by distance-to-plane as a qualitative debug view.
    size = 800
    projected = cloud[:, horizontal_axes]
    lo = np.percentile(projected, 1, axis=0)
    hi = np.percentile(projected, 99, axis=0)
    scale = (size - 32) / np.maximum(hi - lo, 1e-3)
    image = np.zeros((size, size, 3), dtype=np.uint8)
    colors = [(80, 190, 255), (110, 240, 150), (255, 180, 80), (220, 130, 240)]
    for point in projected:
        xy = np.clip(((point - lo) * scale + 16).astype(int), 0, size - 1)
        image[size - 1 - xy[1], xy[0]] = (65, 65, 65)
    for index, plane in enumerate(planes):
        normal = np.asarray(plane["normal"], dtype=np.float32)
        offset = float(plane["offset_m"])
        # Recreate plane support from all projected-height cloud points.
        # The view is intended as qualitative evidence, not a plan.
        support = np.abs(cloud @ normal + offset) <= 0.04
        color = colors[index % len(colors)]
        for point in cloud[support]:
            xy = np.clip(((point[horizontal_axes] - lo) * scale + 16).astype(int), 0, size - 1)
            image[size - 1 - xy[1], xy[0]] = color
    cv2.putText(image, "Vertical-plane candidates (top-down projection; diagnostic)", (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (240, 240, 240), 1, cv2.LINE_AA)
    if not cv2.imwrite(str(path), image):
        raise IOError(f"Could not write wall-plane preview: {path}")
