"""Render diagnostic GeoJSON geometry into a lightweight, vector review sheet."""

import html
import json
from pathlib import Path


WIDTH, HEIGHT = 1100, 760
PLOT = (90, 80, 1010, 620)


def render_geometry_review_svg(geojson_path: Path, svg_path: Path) -> Path:
    data = json.loads(Path(geojson_path).read_text(encoding="utf-8"))
    features = data.get("features", [])
    coordinates = []
    for feature in features:
        geometry = feature.get("geometry") or {}
        if geometry.get("type") == "LineString":
            coordinates.extend(geometry.get("coordinates", []))
        elif geometry.get("type") == "Polygon":
            for ring in geometry.get("coordinates", []):
                coordinates.extend(ring)
    coordinates = [point for point in coordinates if len(point) >= 2]
    if not coordinates:
        raise ValueError("Cannot render geometry review: GeoJSON contains no coordinates.")

    xs, ys = [float(point[0]) for point in coordinates], [float(point[1]) for point in coordinates]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x, span_y = max(max_x - min_x, 0.1), max(max_y - min_y, 0.1)
    plot_x, plot_y, plot_w, plot_h = PLOT
    scale = min(plot_w / span_x, plot_h / span_y)
    offset_x = plot_x + (plot_w - span_x * scale) / 2
    offset_y = plot_y + (plot_h - span_y * scale) / 2

    def pixel(point):
        return offset_x + (float(point[0]) - min_x) * scale, offset_y + (max_y - float(point[1])) * scale

    def points_attr(points):
        return " ".join(f"{x:.1f},{y:.1f}" for x, y in (pixel(point) for point in points))

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="35" y="39" font-family="Arial,sans-serif" font-size="25" font-weight="700" fill="#18212b">Geometry review</text>',
        '<text x="35" y="64" font-family="Arial,sans-serif" font-size="14" font-weight="700" fill="#9d1b1b">DIAGNOSTIC ONLY — NOT AN ACCEPTED FLOOR PLAN</text>',
    ]

    for feature in features:
        geometry = feature.get("geometry") or {}
        kind = feature.get("properties", {}).get("feature_type")
        props = feature.get("properties", {})
        if kind == "observed_floor_coverage" and geometry.get("type") == "Polygon":
            for ring in geometry.get("coordinates", []):
                svg.append(f'<polygon points="{points_attr(ring)}" fill="#e9edf2" stroke="#8b98a5" stroke-width="1.8"/>')

    for feature in features:
        geometry = feature.get("geometry") or {}
        props = feature.get("properties", {})
        kind = props.get("feature_type")
        if kind == "wall_plane_candidate" and geometry.get("type") == "LineString":
            line_points = geometry.get("coordinates", [])
            if len(line_points) < 2:
                continue
            a, b = line_points[:2]
            x1, y1 = pixel(a)
            x2, y2 = pixel(b)
            aligned = props.get("floor_alignment") == "aligned_boundary_candidate"
            color = "#188038" if aligned else "#315f9b"
            svg.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" stroke-width="4" stroke-linecap="round"/>')
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            label = html.escape(str(props.get("candidate_id", "wall")))
            svg.append(f'<text x="{mx + 5:.1f}" y="{my - 6:.1f}" font-family="Arial,sans-serif" font-size="12" fill="{color}">{label}</text>')

    for feature in features:
        geometry = feature.get("geometry") or {}
        props = feature.get("properties", {})
        kind = props.get("feature_type")
        if kind == "boundary_face_hypothesis" and geometry.get("type") == "Polygon":
            ring = geometry.get("coordinates", [[]])[0]
            if len(ring) < 4:
                continue
            svg.append(f'<polygon points="{points_attr(ring)}" fill="#d946ef" fill-opacity="0.16" stroke="#bd21d7" stroke-width="4"/>')
            cx = sum(float(point[0]) for point in ring[:-1]) / max(1, len(ring) - 1)
            cy = sum(float(point[1]) for point in ring[:-1]) / max(1, len(ring) - 1)
            px, py = pixel([cx, cy])
            area = props.get("area_m2")
            svg.append(f'<text x="{px:.1f}" y="{py:.1f}" text-anchor="middle" font-family="Arial,sans-serif" font-size="15" font-weight="700" fill="#8b149f">candidate {area:.2f} m²</text>')
            for index, (a, b) in enumerate(zip(ring[:-1], ring[1:]), start=1):
                length = ((float(b[0]) - float(a[0])) ** 2 + (float(b[1]) - float(a[1])) ** 2) ** 0.5
                mx, my = pixel([(float(a[0]) + float(b[0])) / 2, (float(a[1]) + float(b[1])) / 2])
                svg.append(f'<text x="{mx:.1f}" y="{my - 5:.1f}" text-anchor="middle" font-family="Arial,sans-serif" font-size="12" fill="#77118a">~{length:.2f} m</text>')
        elif kind == "unclassified_boundary_gap" and geometry.get("type") == "LineString":
            line_points = geometry.get("coordinates", [])
            if len(line_points) < 2:
                continue
            a, b = line_points[:2]
            x1, y1 = pixel(a)
            x2, y2 = pixel(b)
            svg.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#d93025" stroke-width="3" stroke-dasharray="8 6"/>')
            label = html.escape(str(props.get("candidate_id", "gap")))
            gap = props.get("gap_extent_m")
            svg.append(f'<text x="{(x1+x2)/2+4:.1f}" y="{(y1+y2)/2-5:.1f}" font-family="Arial,sans-serif" font-size="12" fill="#a61b14">{label}: {gap:.2f} m, unclassified</text>')

    legend_y = 660
    legend = [("#e9edf2", "Observed floor coverage"), ("#188038", "Wall candidate aligned"),
              ("#bd21d7", "Boundary face hypothesis"), ("#d93025", "Unclassified gap")]
    x = 35
    for color, label in legend:
        svg.append(f'<rect x="{x}" y="{legend_y-13}" width="16" height="12" fill="{color}" stroke="#65717e"/>')
        svg.append(f'<text x="{x+23}" y="{legend_y-3}" font-family="Arial,sans-serif" font-size="12" fill="#303943">{label}</text>')
        x += 220 if label != "Boundary face hypothesis" else 235
    svg.append('<text x="35" y="710" font-family="Arial,sans-serif" font-size="12" fill="#5c6670">Capture-local XY; metres assumed. Candidate lengths and area are uncalibrated. Gray outline is observed coverage, not room footprint.</text>')
    svg.append('</svg>')
    Path(svg_path).write_text("\n".join(svg) + "\n", encoding="utf-8")
    return Path(svg_path)
