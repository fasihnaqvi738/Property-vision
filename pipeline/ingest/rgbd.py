"""Reader and lightweight point-cloud exporter for the supplied RGB-D bundle."""

import csv
import json
import math
from pathlib import Path

import numpy as np
import cv2


def _read_odometry(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle, skipinitialspace=True))
    if not rows:
        raise ValueError(f"No odometry records found in {path}.")
    return rows


def _quaternion_matrix(qx: float, qy: float, qz: float, qw: float) -> np.ndarray:
    norm = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
    if norm == 0:
        raise ValueError("Encountered a zero-length odometry quaternion.")
    x, y, z, w = qx / norm, qy / norm, qz / norm, qw / norm
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def _read_synchronized_rgb_frames(
    video_path: Path,
    depth_rows: list[dict[str, str]],
    target_ids: list[str],
    depth_width: int,
    depth_height: int,
) -> tuple[dict[str, np.ndarray], dict]:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise ValueError(f"Could not open RGB video: {video_path}")
    video_frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    video_fps = float(capture.get(cv2.CAP_PROP_FPS))
    video_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    video_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    depth_start = float(depth_rows[0]["timestamp"])
    targets = [
        (frame_id, float(next(r for r in depth_rows if r["frame"].strip() == frame_id)["timestamp"]) - depth_start)
        for frame_id in target_ids
    ]

    def read_frame():
        ok, frame = capture.read()
        if not ok:
            return None
        return capture.get(cv2.CAP_PROP_POS_MSEC) / 1000.0, frame

    current = read_frame()
    previous = None
    resized_rgb: dict[str, np.ndarray] = {}
    offsets = []
    try:
        for frame_id, target_time in targets:
            while current is not None and current[0] < target_time:
                previous = current
                current = read_frame()
            candidates = [item for item in (previous, current) if item is not None]
            if not candidates:
                raise ValueError(f"RGB video ended before depth frame {frame_id} could be matched.")
            matched_time, matched_bgr = min(candidates, key=lambda item: abs(item[0] - target_time))
            offset = matched_time - target_time
            if abs(offset) > 0.050:
                raise ValueError(
                    f"Nearest RGB frame is {abs(offset) * 1000:.1f} ms from depth frame {frame_id}; "
                    "refusing to assign potentially incorrect colors."
                )
            small_bgr = cv2.resize(
                matched_bgr,
                (depth_width, depth_height),
                interpolation=cv2.INTER_AREA,
            )
            resized_rgb[frame_id] = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2RGB)
            offsets.append(offset)
    finally:
        capture.release()

    if video_width / video_height != depth_width / depth_height:
        raise ValueError(
            "RGB video and depth images have different aspect ratios; "
            "pixel-wise color assignment is not supported."
        )
    abs_offsets_ms = np.abs(np.asarray(offsets)) * 1000.0
    sync = {
        "rgb_video_frames_reported": video_frame_count,
        "rgb_video_fps_reported": video_fps,
        "rgb_video_dimensions": [video_width, video_height],
        "depth_dimensions": [depth_width, depth_height],
        "matched_frames": len(resized_rgb),
        "temporal_match_method": "Nearest decoded RGB presentation timestamp to depth odometry timestamp relative to the first frame.",
        "timestamp_origin_assumption": "RGB video frame zero coincides with the first odometry/depth frame; stream durations are closely matched.",
        "absolute_match_offset_ms": {
            "median": round(float(np.median(abs_offsets_ms)), 3),
            "p95": round(float(np.percentile(abs_offsets_ms, 95)), 3),
            "max": round(float(np.max(abs_offsets_ms)), 3),
        },
    }
    return resized_rgb, sync


def _write_ascii_ply(path: Path, points: np.ndarray, colors: np.ndarray) -> None:
    with path.open("w", encoding="ascii", newline="\n") as handle:
        handle.write("ply\nformat ascii 1.0\n")
        handle.write(f"element vertex {len(points)}\n")
        handle.write(
            "property float x\nproperty float y\nproperty float z\n"
            "property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n"
        )
        vertices = np.column_stack((points, colors))
        np.savetxt(handle, vertices, fmt="%.6f %.6f %.6f %d %d %d")


def reconstruct_rgbd(capture_path: Path, output_dir: Path) -> dict:
    """Back-project sparse depth samples into an initial world-frame PLY.

    Depth values are treated as millimeters, and CSV poses as camera-to-world
    transforms. Both assumptions are recorded in the output manifest.
    """
    capture_path = Path(capture_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = _read_odometry(capture_path / "odometry.csv")
    depth_dir = capture_path / "depth"
    depth_files = {p.stem: p for p in depth_dir.glob("*.png")}
    rows_by_frame = {row["frame"].strip(): row for row in rows}
    frame_ids = sorted(set(depth_files) & set(rows_by_frame))
    if not frame_ids:
        raise ValueError("No depth PNG frame IDs match the odometry CSV.")

    frame_stride = 10
    pixel_stride = 4
    depth_scale_to_meters = 0.001
    sampled_frame_ids = frame_ids[::frame_stride]
    first_depth = cv2.imread(str(depth_files[sampled_frame_ids[0]]), cv2.IMREAD_UNCHANGED)
    if first_depth is None or first_depth.ndim != 2:
        raise ValueError(f"Could not read a single-channel depth image: {depth_files[sampled_frame_ids[0]]}")
    depth_height, depth_width = first_depth.shape
    rgb_frames, video_sync = _read_synchronized_rgb_frames(
        capture_path / "rgb.mp4",
        rows,
        sampled_frame_ids,
        depth_width,
        depth_height,
    )
    points_chunks = []
    color_chunks = []
    confidence_histogram: dict[str, int] = {}
    processed = 0

    for frame_id in sampled_frame_ids:
        row = rows_by_frame[frame_id]
        depth = cv2.imread(str(depth_files[frame_id]), cv2.IMREAD_UNCHANGED)
        if depth is None:
            raise ValueError(f"Could not read depth image: {depth_files[frame_id]}")
        depth = np.asarray(depth, dtype=np.float32)
        height, width = depth.shape[:2]
        if depth.ndim != 2:
            raise ValueError(f"Expected single-channel depth image: {depth_files[frame_id]}")

        # Per-frame fx/fy/cx/cy describe the 1920x1440 RGB camera. Scale its
        # intrinsics to the 256x192 depth raster (or the actual PNG dimensions).
        fx = float(row["fx"]) * width / 1920.0
        fy = float(row["fy"]) * height / 1440.0
        cx = float(row["cx"]) * width / 1920.0
        cy = float(row["cy"]) * height / 1440.0
        v, u = np.mgrid[0:height:pixel_stride, 0:width:pixel_stride]
        z = depth[::pixel_stride, ::pixel_stride] * depth_scale_to_meters
        valid = np.isfinite(z) & (z > 0)
        if not np.any(valid):
            continue

        camera_points = np.column_stack((
            ((u[valid] - cx) * z[valid] / fx),
            ((v[valid] - cy) * z[valid] / fy),
            z[valid],
        ))
        rotation = _quaternion_matrix(*(float(row[k]) for k in ("qx", "qy", "qz", "qw")))
        translation = np.array([float(row[k]) for k in ("x", "y", "z")])
        points_chunks.append(camera_points @ rotation.T + translation)
        frame_colors = rgb_frames[frame_id][::pixel_stride, ::pixel_stride]
        color_chunks.append(frame_colors[valid])

        confidence_path = capture_path / "confidence" / f"{frame_id}.png"
        if confidence_path.is_file():
            confidence = cv2.imread(str(confidence_path), cv2.IMREAD_UNCHANGED)
            if confidence is None:
                raise ValueError(f"Could not read confidence image: {confidence_path}")
            values, counts = np.unique(confidence, return_counts=True)
            for value, count in zip(values, counts):
                key = str(int(value))
                confidence_histogram[key] = confidence_histogram.get(key, 0) + int(count)
        processed += 1

    if not points_chunks:
        raise ValueError("The matched depth frames contain no positive depth samples.")
    points = np.concatenate(points_chunks, axis=0).astype(np.float32)
    colors = np.concatenate(color_chunks, axis=0).astype(np.uint8)
    ply_path = output_dir / "rgbd_point_cloud.ply"
    _write_ascii_ply(ply_path, points, colors)

    manifest = {
        "format_version": 1,
        "capture_type": "rgbd",
        "frames_available": len(frame_ids),
        "frames_sampled": processed,
        "frame_stride": frame_stride,
        "pixel_stride": pixel_stride,
        "point_count": int(len(points)),
        "colorization": {
            "source": "rgb.mp4",
            "status": "colored",
            "pixel_alignment_assumption": "RGB and depth are registered to the same camera view; RGB is resized to the depth raster before per-pixel color lookup.",
            "synchronization": video_sync,
        },
        "depth_scale_to_meters": depth_scale_to_meters,
        "depth_unit_assumption": "PNG values interpreted as millimeters; dataset documentation did not confirm units.",
        "camera_intrinsics": "Per-frame RGB-camera intrinsics scaled from 1920x1440 to the depth raster dimensions.",
        "pose_convention_assumption": "CSV quaternion (qx,qy,qz,qw) and translation interpreted as camera-to-world, using standard right-handed quaternion rotation.",
        "confidence_value_pixel_counts": confidence_histogram,
        "artifacts": {"point_cloud": ply_path.name},
        "limitations": [
            "Depth units and pose convention are assumptions and need validation against dataset documentation or a known dimension.",
            "RGB/depth pixel registration and the shared stream start time are inferred from matching aspect ratios, intrinsics, and nearly equal stream durations; they have not been independently ground-truthed.",
            "This is a sampled point cloud, not a floor plan or a survey-grade metric model.",
        ],
    }
    manifest_path = output_dir / "result.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
