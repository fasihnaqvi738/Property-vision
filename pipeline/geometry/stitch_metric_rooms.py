"""Overlap-aware stitching of metric room-shaped candidates from one RGB-D frame."""

from __future__ import annotations

import html
import json
from pathlib import Path

import cv2
import numpy as np


def _area(points: np.ndarray) -> float:
    return abs(float(cv2.contourArea(points.astype(np.float32))))


def _cross2(a: np.ndarray, b: np.ndarray) -> float:
    return float(a[0] * b[1] - a[1] * b[0])


def _shared_edge_length(a: np.ndarray, b: np.ndarray, tolerance_m: float = 0.15) -> float:
    """Return the longest approximately coincident edge overlap, in metres."""
    longest = 0.0
    for i, p0 in enumerate(a):
        p1 = a[(i + 1) % len(a)]
        va = p1 - p0
        la = float(np.linalg.norm(va))
        if la < 0.25:
            continue
        ua = va / la
        for j, q0 in enumerate(b):
            q1 = b[(j + 1) % len(b)]
            vb = q1 - q0
            lb = float(np.linalg.norm(vb))
            if lb < 0.25 or abs(_cross2(ua, vb / lb)) > 0.05:
                continue
            if max(abs(_cross2(ua, q0 - p0)), abs(_cross2(ua, q1 - p0))) > tolerance_m:
                continue
            p_proj = sorted((0.0, la))
            q_proj = sorted((float(np.dot(q0 - p0, ua)), float(np.dot(q1 - p0, ua))))
            overlap = max(0.0, min(p_proj[1], q_proj[1]) - max(p_proj[0], q_proj[0]))
            longest = max(longest, overlap)
    return longest


def stitch_metric_room_candidates(
    boundary_hypotheses: list[dict], *, overlap_tolerance_m2: float = 0.05
) -> dict:
    """Build a review-only scan plan; never promote candidate polygons to rooms.

    All inputs are expected to be in the same sensor world frame. Polygons with
    invalid geometry or overlaps are retained as review candidates and excluded
    from the reported non-overlapping footprint sum.
    """
    footprints: list[dict] = []
    valid: list[tuple[str, np.ndarray, float]] = []
    overlaps: list[dict] = []
    adjacency: list[dict] = []
    for source in boundary_hypotheses or []:
        candidate_id = str(source.get("candidate_id", ""))
        raw = source.get("vertices_xy_m", [])
        try:
            polygon = np.asarray(raw, dtype=np.float64)
        except (TypeError, ValueError):
            polygon = np.empty((0, 2), dtype=np.float64)
        if (not candidate_id or polygon.ndim != 2 or polygon.shape[1] != 2
                or len(polygon) < 3 or not np.isfinite(polygon).all()):
            if candidate_id:
                footprints.append({"candidate_id": candidate_id, "vertices_xy_m": [], "area_m2": None,
                                   "status": "invalid", "reason": "Invalid or non-finite polygon coordinates."})
            continue
        # Remove a duplicate closing vertex for geometry operations.
        if len(polygon) > 3 and np.linalg.norm(polygon[0] - polygon[-1]) < 1e-5:
            polygon = polygon[:-1]
        area = _area(polygon)
        if len(polygon) < 3 or area <= 0.05:
            footprints.append({"candidate_id": candidate_id, "vertices_xy_m": polygon.tolist(), "area_m2": round(area, 4),
                               "status": "invalid", "reason": "Degenerate polygon area."})
            continue

        overlap_found = False
        for other_id, other, other_area in valid:
            # Convex clipping gives a reliable overlap estimate for the common
            # room-shaped convex case. For concave candidates, conservatively
            # reject intersecting bounding boxes rather than double-count area.
            is_convex = cv2.isContourConvex(polygon.astype(np.float32)) and cv2.isContourConvex(other.astype(np.float32))
            aabb_intersects = not (
                polygon[:, 0].max() <= other[:, 0].min() or other[:, 0].max() <= polygon[:, 0].min()
                or polygon[:, 1].max() <= other[:, 1].min() or other[:, 1].max() <= polygon[:, 1].min()
            )
            overlap_area = 0.0
            if aabb_intersects and is_convex:
                try:
                    overlap_area, _ = cv2.intersectConvexConvex(
                        polygon.astype(np.float32), other.astype(np.float32)
                    )
                except cv2.error:
                    overlap_area = min(area, other_area)
            elif aabb_intersects:
                overlap_area = None
            if overlap_area is None or overlap_area > overlap_tolerance_m2:
                overlap_found = True
                overlaps.append({"candidate_a": other_id, "candidate_b": candidate_id,
                                 "intersection_area_m2": round(float(overlap_area), 4) if overlap_area is not None else None,
                                 "status": "excluded_from_footprint",
                                 "reason": "Overlapping candidate polygons are not double-counted."})
            shared = _shared_edge_length(polygon, other)
            if shared >= 0.5:
                adjacency.append({"room_a": other_id, "room_b": candidate_id, "connector": None})

        footprint = {
            "candidate_id": candidate_id,
            "vertices_xy_m": [[round(float(x), 4), round(float(y), 4)] for x, y in polygon],
            "area_m2": round(area, 4),
            "status": "excluded_overlap" if overlap_found else "included_candidate",
        }
        footprints.append(footprint)
        if not overlap_found:
            valid.append((candidate_id, polygon, area))

    accepted_area = sum(item[2] for item in valid)
    if valid:
        status = "partial"
        footprint_measurement = {
            "status": "partial",
            "value": round(accepted_area, 4),
            "unit": "m^2",
            "interval": None,
            "method": "Sum of non-overlapping room-shaped boundary candidates from one metric RGB-D world frame; candidate completeness and scale are unvalidated.",
        }
    else:
        status = "unavailable"
        footprint_measurement = {
            "status": "unavailable", "value": None, "unit": "m^2", "interval": None,
            "method": "No valid closed metric room-shaped boundary candidates were produced by the scan.",
        }
    return {
        "status": status,
        "adjacency": adjacency,
        "footprint": footprint_measurement,
        "overlaps": overlaps,
        "candidate_footprints": footprints,
    }


def write_scan_stitch_artifacts(plan: dict, output_dir: Path) -> tuple[Path, Path]:
    """Write privacy-safe vector review artifacts; source imagery is not copied."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    geojson_path = output_dir / "scan_stitched_plan.geojson"
    svg_path = output_dir / "scan_stitched_plan.svg"
    features = []
    all_xy = []
    for item in plan.get("candidate_footprints", []):
        ring = item.get("vertices_xy_m", [])
        if len(ring) < 3:
            continue
        all_xy.extend(ring)
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [ring + [ring[0]]]},
            "properties": {
                "candidate_id": item["candidate_id"],
                "status": item["status"],
                "area_m2": item.get("area_m2"),
            },
        })
    geojson_path.write_text(json.dumps({
        "type": "FeatureCollection",
        "coordinate_system": {
            "name": "capture_local_metric",
            "units": "m",
            "note": "Local scan frame, not EPSG:4326 or a survey control frame.",
        },
        "features": features,
    }, indent=2) + "\n", encoding="utf-8")

    if all_xy:
        xy = np.asarray(all_xy, dtype=np.float64)
        lo, hi = xy.min(axis=0), xy.max(axis=0)
        span = np.maximum(hi - lo, 0.1)
        width, height, pad = 900, 700, 45
        scale = min((width - pad * 2) / span[0], (height - pad * 2) / span[1])
        def xy_svg(point):
            return (pad + (point[0] - lo[0]) * scale, height - pad - (point[1] - lo[1]) * scale)
        elements = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
                    '<rect width="100%" height="100%" fill="#f8fafc"/>',
                    '<text x="20" y="25" font-family="sans-serif" font-size="16">Scan-derived candidate plan — diagnostic, metric frame unvalidated</text>']
        for item in plan.get("candidate_footprints", []):
            ring = item.get("vertices_xy_m", [])
            if len(ring) < 3:
                continue
            points = " ".join(f"{x:.1f},{y:.1f}" for x, y in map(xy_svg, ring))
            color = "#dc2626" if item["status"] == "excluded_overlap" else "#2563eb"
            elements.append(f'<polygon points="{points}" fill="{color}" fill-opacity="0.18" stroke="{color}" stroke-width="3"/>')
            cx, cy = xy_svg(np.mean(np.asarray(ring), axis=0))
            label = html.escape(f'{item["candidate_id"]} · {item.get("area_m2")} m² · {item["status"]}')
            elements.append(f'<text x="{cx:.1f}" y="{cy:.1f}" text-anchor="middle" font-family="sans-serif" font-size="13">{label}</text>')
        elements.append('</svg>')
        svg_path.write_text("\n".join(elements) + "\n", encoding="utf-8")
    else:
        svg_path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="800" height="120"><text x="20" y="60">No valid scan-derived room candidates</text></svg>\n', encoding="utf-8")
    return geojson_path, svg_path
