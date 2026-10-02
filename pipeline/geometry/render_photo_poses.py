"""Render an explicitly non-metric review of cross-room photo SfM poses."""

import html
from pathlib import Path


def render_photo_pose_diagnostic(diagnostic: dict, output_path: Path) -> Path:
    """Plot per-folder camera-center centroids; never label the plot a floor plan."""
    output_path = Path(output_path)
    rooms = [
        room for room in diagnostic.get("rooms", [])
        if room.get("centroid_sfm_xyz") is not None
    ]
    width, height = 960, 680
    plot = (90, 110, 870, 500)
    xs = [float(room["centroid_sfm_xyz"][0]) for room in rooms]
    ys = [float(room["centroid_sfm_xyz"][1]) for room in rooms]
    span_x = max(max(xs) - min(xs), 0.1) if xs else 1.0
    span_y = max(max(ys) - min(ys), 0.1) if ys else 1.0
    scale = min(plot[2] / span_x, plot[3] / span_y)
    offset_x = plot[0] + (plot[2] - span_x * scale) / 2
    offset_y = plot[1] + (plot[3] - span_y * scale) / 2

    def pixel(room):
        center = room["centroid_sfm_xyz"]
        return (offset_x + (float(center[0]) - min(xs)) * scale,
                offset_y + (max(ys) - float(center[1])) * scale)

    by_id = {room["room_id"]: room for room in rooms}
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#fff"/>',
        '<text x="32" y="38" font-family="Arial,sans-serif" font-size="24" font-weight="700" fill="#17212b">Cross-room photo pose review</text>',
        '<text x="32" y="65" font-family="Arial,sans-serif" font-size="14" font-weight="700" fill="#9d1b1b">DIAGNOSTIC ONLY — NOT A FLOOR PLAN OR METRIC MEASUREMENT</text>',
        '<text x="32" y="92" font-family="Arial,sans-serif" font-size="12" fill="#56616d">Room nodes show registered camera-center centroids projected onto arbitrary SfM X/Y axes.</text>',
    ]
    for link in diagnostic.get("shared_model_room_pairs", []):
        room_a, room_b = by_id.get(link.get("room_a")), by_id.get(link.get("room_b"))
        if room_a and room_b:
            x1, y1 = pixel(room_a)
            x2, y2 = pixel(room_b)
            parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#697586" stroke-width="2" stroke-dasharray="7 6"/>')
    for room in rooms:
        x, y = pixel(room)
        label = html.escape(str(room["room_id"]))
        count = int(room.get("registered_camera_count", 0))
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="11" fill="#2367a8" stroke="#fff" stroke-width="3"/>')
        parts.append(f'<text x="{x + 16:.1f}" y="{y - 4:.1f}" font-family="Arial,sans-serif" font-size="14" font-weight="700" fill="#17212b">{label}</text>')
        parts.append(f'<text x="{x + 16:.1f}" y="{y + 14:.1f}" font-family="Arial,sans-serif" font-size="11" fill="#56616d">{count} registered camera(s)</text>')
    if not rooms:
        parts.append('<text x="480" y="330" text-anchor="middle" font-family="Arial,sans-serif" font-size="18" fill="#56616d">No registered cross-room camera poses were available.</text>')
    parts.extend([
        '<text x="32" y="645" font-family="Arial,sans-serif" font-size="12" fill="#56616d">Dashed lines mean shared COLMAP model membership only; they do not establish adjacency, room shape, scale, or no-overlap.</text>',
        '</svg>',
    ])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return output_path
