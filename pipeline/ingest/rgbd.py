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


def _write_ascii_ply(path: Path, points: np.ndarray) -> None:
    with path.open("w", encoding="ascii", newline="\n") as handle:
        handle.write("ply\nformat ascii 1.0\n")
        handle.write(f"element vertex {len(points)}\n")
        handle.write("property float x\nproperty float y\nproperty float z\nend_header\n")
        np.savetxt(handle, points, fmt="%.6f %.6f %.6f")


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
    points_chunks = []
    confidence_histogram: dict[str, int] = {}
    processed = 0

    for frame_id in frame_ids[::frame_stride]:
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
    ply_path = output_dir / "rgbd_point_cloud.ply"
    _write_ascii_ply(ply_path, points)

    manifest = {
        "format_version": 1,
        "capture_type": "rgbd",
        "frames_available": len(frame_ids),
        "frames_sampled": processed,
        "frame_stride": frame_stride,
        "pixel_stride": pixel_stride,
        "point_count": int(len(points)),
        "depth_scale_to_meters": depth_scale_to_meters,
        "depth_unit_assumption": "PNG values interpreted as millimeters; dataset documentation did not confirm units.",
        "camera_intrinsics": "Per-frame RGB-camera intrinsics scaled from 1920x1440 to the depth raster dimensions.",
        "pose_convention_assumption": "CSV quaternion (qx,qy,qz,qw) and translation interpreted as camera-to-world, using standard right-handed quaternion rotation.",
        "confidence_value_pixel_counts": confidence_histogram,
        "artifacts": {"point_cloud": ply_path.name},
        "limitations": [
            "Depth units and pose convention are assumptions and need validation against dataset documentation or a known dimension.",
            "The RGB video is not colorized because frame timing and camera/depth alignment have not been verified.",
            "This is a sampled point cloud, not a floor plan or a survey-grade metric model.",
        ],
    }
    manifest_path = output_dir / "result.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
