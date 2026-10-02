"""Validate and render a manually traced, dimensioned reference floor plan.

The SVG/GeoJSON preserve source-image pixel coordinates. Printed dimensions are
reported as source-plan references and are not silently used to calibrate the
raster or a photo/video reconstruction.
"""

import argparse
import base64
import json
from pathlib import Path

import cv2
import numpy as np


def _validate_polygon(polygon: list, width: int, height: int, label: str) -> np.ndarray:
    points = np.asarray(polygon, dtype=np.float64)
    if points.ndim != 2 or points.shape[0] < 3 or points.shape[1] != 2:
        raise ValueError(f"{label} needs a polygon with at least three XY vertices.")
    if not np.isfinite(points).all():
        raise ValueError(f"{label} contains a non-finite vertex.")
    if (points[:, 0] < 0).any() or (points[:, 0] > width).any() or (points[:, 1] < 0).any() or (points[:, 1] > height).any():
        raise ValueError(f"{label} has vertices outside the source floor-plan image.")
    area = abs(cv2.contourArea(points.astype(np.float32)))
    if area <= 0:
        raise ValueError(f"{label} has zero area.")
    return np.rint(points).astype(np.int32)


def render_reference_plan(annotation_path: Path, output_dir: Path) -> dict:
    annotation_path = Path(annotation_path).resolve()
    data = json.loads(annotation_path.read_text(encoding="utf-8"))
    source = (annotation_path.parent / data["source"]["floor_plan_image"]).resolve()
    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(f"Could not read floor-plan image: {source}")
    height, width = image.shape[:2]
    expected = (data["source"]["image_width_px"], data["source"]["image_height_px"])
    if (width, height) != tuple(expected):
        raise ValueError(f"Floor-plan raster is {width}x{height}, annotation expects {expected[0]}x{expected[1]}.")

    spaces = []
    for collection in ("rooms", "connectors"):
        for item in data.get(collection, []):
            key = "room_id" if collection == "rooms" else "connector_id"
            label = item[key]
            polygon = _validate_polygon(item["polygon_px"], width, height, label)
            mask = np.zeros((height, width), dtype=np.uint8)
            cv2.fillPoly(mask, [polygon], 1)
            spaces.append((label, item, polygon, mask, collection))

    overlaps = []
    for i, (label_a, *_a, mask_a, _ca) in enumerate(spaces):
        for label_b, *_b, mask_b, _cb in spaces[i + 1:]:
            intersection_px = int(np.logical_and(mask_a, mask_b).sum())
            if intersection_px > 4:
                overlaps.append({"space_a": label_a, "space_b": label_b, "intersection_pixels": intersection_px})
    if overlaps:
        raise ValueError(f"Reference plan polygons overlap: {overlaps}")

    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    colors = ["#00a6a6", "#ff8c42", "#8e6cdb", "#4c9f70", "#d1495b", "#3d85c6", "#e1b12c", "#8d6e63"]
    legend_width = 520
    canvas_width = width + legend_width
    canvas_height = height + 100
    display_ids = {label: label.split("_", maxsplit=1)[0] for label, *_ in spaces}
    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_width}" height="{canvas_height}" viewBox="0 0 {canvas_width} {canvas_height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<image x="0" y="90" width="{width}" height="{height}" href="data:image/jpeg;base64,{base64.b64encode(source.read_bytes()).decode("ascii")}"/>',
        '<text x="20" y="30" font-family="Arial" font-size="22" font-weight="bold" fill="#17212b">Apartment multi-room reference plan</text>',
        '<text x="20" y="55" font-family="Arial" font-size="13" fill="#8b1e1e">MANUAL TRACE OF SUPPLIED DRAWING — pixel-coordinate geometry; printed dimensions are plan references</text>',
        '<text x="20" y="75" font-family="Arial" font-size="12" fill="#394b59">Opening widths unavailable. No apartment LiDAR was supplied. Room adjacency transcribed from the drawing.</text>',
        f'<text x="{width + 18}" y="30" font-family="Arial" font-size="17" font-weight="bold" fill="#17212b">Plan key</text>',
        f'<text x="{width + 18}" y="51" font-family="Arial" font-size="11" fill="#536471">Color tags identify traced spaces. Dimensions are copied from the drawing.</text>',
    ]
    geojson = {"type": "FeatureCollection", "name": data["case_id"], "coordinate_reference": "source_image_pixels_origin_top_left", "features": []}
    for index, (label, item, polygon, _mask, collection) in enumerate(spaces):
        color = colors[index % len(colors)]
        points = " ".join(f"{x},{y + 90}" for x, y in polygon.tolist())
        svg_parts.append(f'<polygon points="{points}" fill="{color}" fill-opacity="0.14" stroke="{color}" stroke-width="3"/>')
        display = item.get("plan_label", label)
        dim = item.get("dimension_source_text") or item.get("width_source_text")
        center = polygon.mean(axis=0)
        tag_x = float(center[0]) - 20
        tag_y = float(center[1]) + 90
        svg_parts.append(f'<rect x="{tag_x:.1f}" y="{tag_y - 13:.1f}" width="40" height="20" rx="4" fill="#17212b" stroke="{color}" stroke-width="2"/>')
        svg_parts.append(f'<text x="{center[0]:.1f}" y="{tag_y + 1:.1f}" text-anchor="middle" font-family="Arial" font-size="10" font-weight="bold" fill="#ffffff">{display_ids[label]}</text>')
        key_y = 82 + (index + 1) * 25
        svg_parts.append(f'<rect x="{width + 18}" y="{key_y - 10}" width="13" height="13" fill="{color}"/>')
        svg_parts.append(f'<text x="{width + 40}" y="{key_y}" font-family="Arial" font-size="11" fill="#17212b">{display_ids[label]}: {display} {("— " + dim) if dim else ""}</text>')
        ring = polygon.tolist() + [polygon[0].tolist()]
        props = dict(item)
        props.pop("polygon_px", None)
        props.update({"space_type": item.get("space_kind", collection[:-1]), "plan_label": display, "geometry_status": "manual_reference_trace"})
        geojson["features"].append({"type": "Feature", "properties": props, "geometry": {"type": "Polygon", "coordinates": [ring]}})

    adjacency_title_y = 100 + len(spaces) * 25 + 20
    svg_parts.append(f'<text x="{width + 18}" y="{adjacency_title_y}" font-family="Arial" font-size="13" font-weight="bold" fill="#17212b">Adjacency transcribed from plan</text>')
    for edge_index, edge in enumerate(data.get("adjacency", [])):
        row_y = adjacency_title_y + 20 + edge_index * 17
        a = display_ids.get(edge["space_a"], edge["space_a"])
        b = display_ids.get(edge["space_b"], edge["space_b"])
        connection = edge.get("connection", "connection")
        svg_parts.append(f'<text x="{width + 18}" y="{row_y}" font-family="Arial" font-size="10" fill="#394b59">{a} -- {b}: {connection}</text>')

    preview = np.full((canvas_height, canvas_width, 3), 255, dtype=np.uint8)
    preview[90:90 + height, :width] = image
    cv2.putText(preview, "Apartment multi-room reference plan", (20, 31), cv2.FONT_HERSHEY_SIMPLEX, 0.67, (43, 33, 23), 2, cv2.LINE_AA)
    cv2.putText(preview, "MANUAL TRACE - pixel-coordinate geometry; dimensions are references from the drawing", (20, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.39, (30, 30, 139), 1, cv2.LINE_AA)
    cv2.putText(preview, "No apartment LiDAR supplied. Adjacency transcribed; opening widths unavailable.", (20, 76), cv2.FONT_HERSHEY_SIMPLEX, 0.37, (59, 75, 89), 1, cv2.LINE_AA)
    cv2.putText(preview, "Plan key", (width + 18, 31), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (43, 33, 23), 2, cv2.LINE_AA)
    cv2.putText(preview, "Color tags identify traced spaces. Dimensions copied from source drawing.", (width + 18, 51), cv2.FONT_HERSHEY_SIMPLEX, 0.31, (71, 100, 116), 1, cv2.LINE_AA)
    fill = image.copy()
    for index, (label, item, polygon, _mask, _collection) in enumerate(spaces):
        color = tuple(int(colors[index % len(colors)].lstrip("#")[i:i + 2], 16) for i in (4, 2, 0))
        cv2.fillPoly(fill, [polygon], color)
    overlay = cv2.addWeighted(fill, 0.22, image, 0.78, 0)
    preview[90:90 + height, :width] = overlay
    for index, (label, item, polygon, _mask, _collection) in enumerate(spaces):
        color = tuple(int(colors[index % len(colors)].lstrip("#")[i:i + 2], 16) for i in (4, 2, 0))
        shifted = polygon.copy()
        shifted[:, 1] += 90
        cv2.polylines(preview, [shifted], True, color, 2, cv2.LINE_AA)
        center = np.rint(polygon.mean(axis=0)).astype(int)
        center[1] += 90
        cv2.rectangle(preview, (center[0] - 22, center[1] - 15), (center[0] + 22, center[1] + 9), (28, 33, 39), -1, cv2.LINE_AA)
        cv2.rectangle(preview, (center[0] - 22, center[1] - 15), (center[0] + 22, center[1] + 9), color, 2, cv2.LINE_AA)
        cv2.putText(preview, display_ids[label], (center[0] - 18, center[1] + 2), cv2.FONT_HERSHEY_SIMPLEX, 0.34, (255, 255, 255), 1, cv2.LINE_AA)

        key_y = 82 + (index + 1) * 25
        cv2.rectangle(preview, (width + 18, key_y - 11), (width + 31, key_y + 2), color, -1)
        display = item.get("plan_label", label)
        dim = item.get("dimension_source_text") or item.get("width_source_text") or ""
        caption = f"{display_ids[label]}: {display} {('— ' + dim) if dim else ''}"
        cv2.putText(preview, caption, (width + 40, key_y), cv2.FONT_HERSHEY_SIMPLEX, 0.39, (35, 43, 51), 1, cv2.LINE_AA)

    adjacency_title_y_cv = 100 + len(spaces) * 25 + 20
    cv2.putText(preview, "Adjacency transcribed from plan", (width + 18, adjacency_title_y_cv), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (30, 35, 43), 1, cv2.LINE_AA)
    for edge_index, edge in enumerate(data.get("adjacency", [])):
        row_y = adjacency_title_y_cv + 20 + edge_index * 17
        a = display_ids.get(edge["space_a"], edge["space_a"])
        b = display_ids.get(edge["space_b"], edge["space_b"])
        caption = f"{a} -- {b}: {edge.get('connection', 'connection')}"
        cv2.putText(preview, caption[:76], (width + 18, row_y), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (57, 75, 89), 1, cv2.LINE_AA)

    svg_parts.append('</svg>')
    svg_path = output_dir / "stitched_reference_plan.svg"
    svg_path.write_text("\n".join(svg_parts) + "\n", encoding="utf-8")
    preview_path = output_dir / "stitched_reference_plan_preview.png"
    if not cv2.imwrite(str(preview_path), preview):
        raise IOError(f"Could not write preview image: {preview_path}")
    geojson["features"].append({"type": "Feature", "properties": {"feature_type": "room_adjacency", "edges": data.get("adjacency", [])}, "geometry": None})
    geojson_path = output_dir / "stitched_reference_plan.geojson"
    geojson_path.write_text(json.dumps(geojson, indent=2) + "\n", encoding="utf-8")
    report = {
        "case_id": data["case_id"],
        "status": "manual_reference_plan_rendered",
        "room_count": sum(room.get("space_kind", "room") in {"room", "lobby"} for room in data.get("rooms", [])),
        "ancillary_space_count": sum(room.get("space_kind") in {"bathroom", "walk_in_closet"} for room in data.get("rooms", [])),
        "connector_count": len(data.get("connectors", [])),
        "adjacency_count": len(data.get("adjacency", [])),
        "overlap_pair_count": 0,
        "overlap_check": "No polygon intersections above four raster pixels in the traced source-image coordinate frame.",
        "dimension_count": sum(bool(room.get("dimensions_m")) for room in data.get("rooms", [])),
        "dimension_status": "transcribed_from_source_plan_not_independently_measured",
        "opening_widths_available": sum(edge.get("opening_width_m") is not None for edge in data.get("adjacency", [])),
        "source_limitations": data["source"]["limitations"],
        "artifacts": {"svg": str(svg_path), "png_preview": str(preview_path), "geojson": str(geojson_path)},
    }
    (output_dir / "plan_validation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("annotation_json", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(render_reference_plan(args.annotation_json, args.output_dir), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
