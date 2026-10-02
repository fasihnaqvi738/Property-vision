"""Diagnostic floor-return projection for RGB-D scans.

This creates evidence for later room-boundary extraction. Connected floor
return components are coverage regions, not asserted room footprints.
"""

from pathlib import Path

import cv2
import numpy as np


def analyze_floor_returns(
    points: np.ndarray,
    pose_translations: np.ndarray,
    output_dir: Path,
    *,
    grid_resolution_m: float = 0.05,
) -> dict:
    points = np.asarray(points, dtype=np.float32)
    translations = np.asarray(pose_translations, dtype=np.float32)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) == 0:
        raise ValueError("Floor analysis requires a non-empty N x 3 point array.")
    if translations.ndim != 2 or translations.shape[1] != 3 or len(translations) == 0:
        raise ValueError("Floor analysis requires camera pose translations.")

    # The least-varying camera-translation axis is used as a provisional
    # vertical axis. This is a capture-specific heuristic, not a guarantee.
    translation_spans = np.ptp(translations, axis=0)
    vertical_axis = int(np.argmin(translation_spans))
    horizontal_axes = [axis for axis in range(3) if axis != vertical_axis]
    vertical = points[:, vertical_axis]
    lower_decile = float(np.percentile(vertical, 10))
    lower_returns = vertical[vertical <= lower_decile]
    bin_edges = np.arange(
        float(lower_returns.min()) - 0.005,
        float(lower_returns.max()) + 0.015,
        0.01,
    )
    counts, edges = np.histogram(lower_returns, bins=bin_edges)
    floor_level = float((edges[int(np.argmax(counts))] + edges[int(np.argmax(counts)) + 1]) / 2)

    floor_band_m = 0.06
    floor_mask = np.abs(vertical - floor_level) <= floor_band_m
    horizontal_a = points[floor_mask, horizontal_axes[0]]
    horizontal_b = points[floor_mask, horizontal_axes[1]]
    if len(horizontal_a) == 0:
        raise ValueError("No points fell within the provisional floor-return band.")

    a_min, a_max = float(horizontal_a.min()), float(horizontal_a.max())
    b_min, b_max = float(horizontal_b.min()), float(horizontal_b.max())
    a_edges = np.arange(a_min, a_max + grid_resolution_m, grid_resolution_m)
    b_edges = np.arange(b_min, b_max + grid_resolution_m, grid_resolution_m)
    histogram, _, _ = np.histogram2d(horizontal_a, horizontal_b, bins=(a_edges, b_edges))
    occupancy = (histogram >= 3).astype(np.uint8)
    occupancy = cv2.morphologyEx(
        occupancy,
        cv2.MORPH_CLOSE,
        np.ones((3, 3), dtype=np.uint8),
    )
    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(occupancy, connectivity=8)
    min_component_cells = max(20, int(round(0.20 / (grid_resolution_m ** 2))))
    candidates = [
        (label, int(stats[label, cv2.CC_STAT_AREA]))
        for label in range(1, component_count)
        if int(stats[label, cv2.CC_STAT_AREA]) >= min_component_cells
    ]
    candidates.sort(key=lambda item: item[1], reverse=True)

    coverage_outline = None
    coverage_outline_area = None
    coverage_component_label = None
    coverage_mask = None
    if candidates:
        coverage_component_label = candidates[0][0]
        coverage_mask = (labels == coverage_component_label).astype(np.uint8)
        contours, _ = cv2.findContours(coverage_mask.T, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            contour = max(contours, key=cv2.contourArea)
            simplified = cv2.approxPolyDP(contour, 1.5, True).reshape(-1, 2)
            coverage_outline = [
                [
                    round(float(a_edges[int(a_index)] + grid_resolution_m / 2), 3),
                    round(float(b_edges[int(b_index)] + grid_resolution_m / 2), 3),
                ]
                for a_index, b_index in simplified
            ]
            if len(coverage_outline) >= 3:
                coverage_outline.append(coverage_outline[0])
                coverage_outline_area = round(
                    abs(float(cv2.contourArea(contour))) * grid_resolution_m ** 2, 3
                )
            else:
                coverage_outline = None

    preview = np.zeros(occupancy.shape, dtype=np.uint8)
    for order, (label, _) in enumerate(candidates):
        preview[labels == label] = 220 if order == 0 else 120
    preview = cv2.flip(preview.T, 0)
    image = cv2.cvtColor(preview, cv2.COLOR_GRAY2BGR)
    if coverage_mask is not None:
        contours, _ = cv2.findContours(coverage_mask.T, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        outline_pixels = []
        b_count = coverage_mask.shape[1]
        for contour in contours:
            mapped = contour.copy()
            mapped[:, 0, 1] = b_count - 1 - mapped[:, 0, 1]
            outline_pixels.append(mapped)
        if outline_pixels:
            cv2.drawContours(image, outline_pixels, -1, (0, 140, 255), 1, cv2.LINE_AA)
    image = cv2.resize(image, (image.shape[1] * 4, image.shape[0] * 4), interpolation=cv2.INTER_NEAREST)
    image = cv2.copyMakeBorder(image, 42, 20, 20, 20, cv2.BORDER_CONSTANT, value=(0, 0, 0))
    cv2.putText(
        image,
        f"Floor-return coverage only | axis={('xyz'[vertical_axis])} | level={floor_level:.2f} m | grid={grid_resolution_m:.2f} m",
        (12, 28),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (80, 230, 120),
        1,
        cv2.LINE_AA,
    )
    preview_path = Path(output_dir) / "floor_return_preview.png"
    if not cv2.imwrite(str(preview_path), image):
        raise IOError(f"Could not write floor-return preview: {preview_path}")

    return {
        "status": "diagnostic_only",
        "vertical_axis_assumption": "Least-varying world-axis span of camera translations; must be confirmed against gravity/ground truth.",
        "vertical_axis": "xyz"[vertical_axis],
        "camera_translation_spans_m": [round(float(x), 4) for x in translation_spans],
        "provisional_floor_level_m": round(floor_level, 4),
        "floor_return_band_m": floor_band_m,
        "floor_return_point_count": int(floor_mask.sum()),
        "grid_resolution_m": grid_resolution_m,
        "candidate_coverage_components": [
            {
                "label": label,
                "occupied_cells": cells,
                "observed_cell_area_m2": round(cells * grid_resolution_m ** 2, 3),
            }
            for label, cells in candidates
        ],
        "largest_component_coverage_outline": {
            "status": "diagnostic_only" if coverage_outline else "unavailable",
            "component_label": coverage_component_label,
            "coordinates_axes": ["xyz"[horizontal_axes[0]], "xyz"[horizontal_axes[1]]],
            "vertices_m": coverage_outline or [],
            "vertex_count": max(0, len(coverage_outline or []) - 1),
            "observed_cell_area_m2": round(candidates[0][1] * grid_resolution_m ** 2, 3) if candidates else None,
            "outline_area_m2": coverage_outline_area,
            "limitations": [
                "This polygon outlines the connected area of observed floor returns, not a verified room footprint.",
                "Furniture, occlusion, incomplete scan coverage, floor-level error, and pose drift can change this outline.",
                "No room identity, wall boundary, opening, or calibrated confidence interval is inferred.",
            ],
        },
        "preview": preview_path.name,
        "limitations": [
            "The vertical-axis and floor-level heuristics are provisional.",
            "Occupied cells measure observed floor-return coverage, not room floor area.",
            "Coverage components are not room segmentation and do not identify openings or adjacency.",
        ],
    }
