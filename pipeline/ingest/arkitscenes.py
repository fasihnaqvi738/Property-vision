"""Minimal reader for timestamped ARKitScenes raw RGB-D captures.

The ARKitScenes source data is not copied into the repository. This module
joins its low-resolution Apple LiDAR depth/confidence frames, wide RGB frames,
per-frame intrinsics, and sparse camera trajectory for local processing.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass(frozen=True)
class ARKitFrame:
    frame_id: str
    timestamp: float
    rgb_path: Path
    depth_path: Path
    confidence_path: Path
    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float
    rotation_camera_to_world: np.ndarray
    translation_camera_to_world_m: np.ndarray
    rgb_offset_s: float
    depth_offset_s: float
    confidence_offset_s: float
    intrinsics_offset_s: float


def is_arkitscenes_raw_capture(path: Path) -> bool:
    """Return whether path has the required ARKitScenes raw asset layout."""
    return all(
        item.exists()
        for item in (
            path / "lowres_wide",
            path / "lowres_depth",
            path / "confidence",
            path / "lowres_wide_intrinsics",
            path / "lowres_wide.traj",
        )
    ) and all(
        (path / name).is_dir()
        for name in ("lowres_wide", "lowres_depth", "confidence", "lowres_wide_intrinsics")
    )


def _timestamp(path: Path) -> float:
    """Read the trailing timestamp token from an ARKitScenes asset filename."""
    token = path.stem.rsplit("_", 1)[-1]
    try:
        return float(token)
    except ValueError as error:
        raise ValueError(f"Could not read an ARKitScenes timestamp from {path.name}.") from error


def _timestamped_files(directory: Path, suffix: str) -> list[tuple[float, Path]]:
    files = [( _timestamp(path), path) for path in directory.glob(f"*{suffix}") if path.is_file()]
    return sorted(files, key=lambda item: (item[0], item[1].name))


def _nearest(
    items: list[tuple[float, Path]], timestamps: list[float], target: float,
) -> tuple[Path, float] | None:
    if not items:
        return None
    index = bisect_left(timestamps, target)
    candidates = [items[i] for i in (index - 1, index) if 0 <= i < len(items)]
    stamp, path = min(candidates, key=lambda item: (abs(item[0] - target), item[0]))
    return path, stamp - target


def _read_intrinsics(path: Path) -> tuple[int, int, float, float, float, float]:
    values = np.fromstring(path.read_text(encoding="utf-8").strip(), sep=" ")
    if values.size != 6 or not np.isfinite(values).all():
        raise ValueError(f"Expected six finite pincam fields in {path}.")
    width, height, fx, fy, cx, cy = values.tolist()
    if width <= 0 or height <= 0 or fx <= 0 or fy <= 0:
        raise ValueError(f"Invalid image size or focal length in {path}.")
    return int(width), int(height), float(fx), float(fy), float(cx), float(cy)


def _read_trajectory(path: Path) -> list[tuple[float, np.ndarray, np.ndarray]]:
    poses = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        values = np.fromstring(stripped, sep=" ")
        if values.size != 7 or not np.isfinite(values).all():
            raise ValueError(
                f"Expected timestamp, 3 axis-angle values, and 3 translations at "
                f"{path}:{line_number}."
            )
        timestamp = float(values[0])
        axis_angle = values[1:4].astype(np.float64).reshape(3, 1)
        rotation, _ = cv2.Rodrigues(axis_angle)
        translation = values[4:7].astype(np.float64)
        poses.append((timestamp, rotation, translation))
    if not poses:
        raise ValueError(f"No camera poses found in {path}.")
    return sorted(poses, key=lambda item: item[0])


def load_arkitscenes_frames(
    capture_path: Path, *, max_timestamp_offset_s: float = 0.050,
) -> tuple[list[ARKitFrame], dict]:
    """Join RGB-D/intrinsics to sparse poses, refusing distant timestamp matches.

    The released trajectory samples are sparse. Each pose is therefore matched
    to the nearest available timestamp in each sensor stream, subject to the
    explicit offset limit; unmatched or duplicate RGB poses are skipped.
    """
    capture_path = Path(capture_path)
    if max_timestamp_offset_s <= 0:
        raise ValueError("max_timestamp_offset_s must be positive.")
    if not is_arkitscenes_raw_capture(capture_path):
        raise ValueError(
            "Expected an ARKitScenes raw video folder containing lowres_wide/, "
            "lowres_depth/, confidence/, lowres_wide_intrinsics/, and lowres_wide.traj."
        )

    rgb = _timestamped_files(capture_path / "lowres_wide", ".png")
    depth = _timestamped_files(capture_path / "lowres_depth", ".png")
    confidence = _timestamped_files(capture_path / "confidence", ".png")
    intrinsics = _timestamped_files(capture_path / "lowres_wide_intrinsics", ".pincam")
    streams = {
        "rgb": (rgb, [item[0] for item in rgb]),
        "depth": (depth, [item[0] for item in depth]),
        "confidence": (confidence, [item[0] for item in confidence]),
        "intrinsics": (intrinsics, [item[0] for item in intrinsics]),
    }

    frames: list[ARKitFrame] = []
    used_rgb: set[Path] = set()
    rejected_offsets = 0
    for pose_index, (timestamp, rotation, translation) in enumerate(
        _read_trajectory(capture_path / "lowres_wide.traj"), start=1
    ):
        matches = {
            name: _nearest(items, times, timestamp)
            for name, (items, times) in streams.items()
        }
        if any(match is None or abs(match[1]) > max_timestamp_offset_s for match in matches.values()):
            rejected_offsets += 1
            continue
        rgb_path, rgb_offset = matches["rgb"]
        depth_path, depth_offset = matches["depth"]
        confidence_path, confidence_offset = matches["confidence"]
        intrinsics_path, intrinsics_offset = matches["intrinsics"]
        if rgb_path in used_rgb:
            continue
        used_rgb.add(rgb_path)
        width, height, fx, fy, cx, cy = _read_intrinsics(intrinsics_path)
        frames.append(ARKitFrame(
            frame_id=f"arkit_{pose_index:06d}",
            timestamp=timestamp,
            rgb_path=rgb_path,
            depth_path=depth_path,
            confidence_path=confidence_path,
            width=width,
            height=height,
            fx=fx,
            fy=fy,
            cx=cx,
            cy=cy,
            rotation_camera_to_world=rotation,
            translation_camera_to_world_m=translation,
            rgb_offset_s=rgb_offset,
            depth_offset_s=depth_offset,
            confidence_offset_s=confidence_offset,
            intrinsics_offset_s=intrinsics_offset,
        ))

    if not frames:
        raise ValueError(
            "No ARKitScenes poses could be joined to RGB, depth, confidence, and "
            f"intrinsics within {max_timestamp_offset_s * 1000:.0f} ms. Check the input asset folders."
        )
    offsets_ms = {
        name: np.abs(np.asarray([getattr(frame, f"{name}_offset_s") for frame in frames])) * 1000
        for name in ("rgb", "depth", "confidence", "intrinsics")
    }
    sync = {
        "method": "Nearest timestamp for each available lowres_wide.traj pose; duplicate RGB frames skipped.",
        "max_allowed_offset_ms": round(max_timestamp_offset_s * 1000, 3),
        "joined_pose_count": len(frames),
        "rejected_pose_count_due_to_missing_or_distant_stream_frames": rejected_offsets,
        "absolute_timestamp_offset_ms": {
            name: {
                "median": round(float(np.median(values)), 3),
                "p95": round(float(np.percentile(values, 95)), 3),
                "max": round(float(np.max(values)), 3),
            }
            for name, values in offsets_ms.items()
        },
    }
    return frames, sync
