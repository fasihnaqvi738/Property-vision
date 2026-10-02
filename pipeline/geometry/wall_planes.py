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
        height_m = float(np.percentile(height, 98) - np.percentile(height, 2))
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
    preview_path = Path(output_dir) / "wall_plane_candidates.png"
    _write_preview(cloud, planes, v_axis, h_axes, preview_path)
    boundary_preview_path = Path(output_dir) / "wall_boundary_diagnostic.png"
    _write_boundary_preview(planes, boundaries, boundary_preview_path)
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


def _write_boundary_preview(planes: list[dict], boundaries: dict, path: Path) -> None:
    """Render a top-down diagnostic of candidate spans and unresolved endpoint gaps."""
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

    endpoints = np.concatenate(segments, axis=0)
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

    cv2.putText(canvas, "Wall boundary candidates (diagnostic only)", (40, 38),
                cv2.FONT_HERSHEY_SIMPLEX, 0.85, (35, 35, 35), 2, cv2.LINE_AA)
    for index, plane in enumerate(planes):
        points = plane.get("projected_endpoints_m", [])
        if len(points) != 2:
            continue
        a, b = pixel(np.asarray(points[0])), pixel(np.asarray(points[1]))
        cv2.line(canvas, a, b, (180, 110, 20), 3, cv2.LINE_AA)
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

    cv2.putText(canvas, "Orange: observed endpoints   Blue: fitted wall spans   Red: unresolved gaps",
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
