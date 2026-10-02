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
        planes.append({
            "normal": [round(float(value), 5) for value in normal],
            "offset_m": round(float(-np.dot(normal, centroid)), 5),
            "point_count": int(len(patch)),
            "observed_length_m": round(length_m, 3),
            "observed_height_m": round(height_m, 3),
            "observed_patch_area_m2": round(length_m * height_m, 3),
            "fit_inlier_fraction": round(len(patch) / max(1, len(cloud)), 4),
            "candidate_gaps": _find_candidate_gaps(patch, tangent, v_axis, floor),
        })
        residual[inlier_indices] = False

    planes.sort(key=lambda plane: plane["point_count"], reverse=True)
    preview_path = Path(output_dir) / "wall_plane_candidates.png"
    _write_preview(cloud, planes, v_axis, h_axes, preview_path)
    return {
        "status": "diagnostic_only",
        "vertical_axis": vertical_axis,
        "floor_level_source": "Provisional floor-return estimate; positive axis direction assumed upward.",
        "input_point_count": int(len(points)),
        "points_in_height_band": int(mask.sum()),
        "voxel_resolution_m": voxel,
        "ransac_distance_threshold_m": distance_threshold,
        "candidate_count": len(planes),
        "wall_plane_candidates": [
            {"candidate_id": f"wall_candidate_{index + 1}", **plane}
            for index, plane in enumerate(planes)
        ],
        "preview": preview_path.name,
        "limitations": [
            "Plane lengths, heights, and patch areas describe sampled planar support, not verified room dimensions or complete surface areas.",
            "Candidate extent values are uncalibrated diagnostics and do not have validated confidence intervals.",
            "Candidate gaps are missing-return regions and may result from occlusion, sparse sampling, or reconstruction error; they are not classified openings.",
            "Gravity orientation, depth scale, camera registration, and pose accuracy remain unvalidated against ground truth.",
            "Room boundaries, adjacency, opening dimensions, and a rendered floor plan are not produced.",
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
