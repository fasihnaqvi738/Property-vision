"""Compare ARKitScenes low-resolution LiDAR depth with FARO-projected depth."""

from __future__ import annotations

import argparse
import bisect
import json
from pathlib import Path

import cv2
import numpy as np

from pipeline.ingest.arkitscenes import load_arkitscenes_frames


def _timestamped_pngs(directory: Path) -> list[tuple[float, Path]]:
    files = []
    for path in directory.glob("*.png"):
        try:
            timestamp = float(path.stem.rsplit("_", 1)[-1])
        except ValueError:
            continue
        files.append((timestamp, path))
    return sorted(files, key=lambda item: (item[0], item[1].name))


def _nearest(items: list[tuple[float, Path]], timestamps: list[float], target: float):
    index = bisect.bisect_left(timestamps, target)
    candidates = [items[i] for i in (index - 1, index) if 0 <= i < len(items)]
    if not candidates:
        return None
    timestamp, path = min(candidates, key=lambda item: (abs(item[0] - target), item[0]))
    return path, timestamp - target


def evaluate_depth(
    capture_dir: Path,
    *,
    max_timestamp_offset_s: float = 0.060,
    pixel_stride: int = 2,
) -> dict:
    capture_dir = Path(capture_dir)
    if max_timestamp_offset_s <= 0 or pixel_stride < 1:
        raise ValueError("Timestamp tolerance and pixel stride must be positive.")
    reference_dir = capture_dir / "highres_depth"
    references = _timestamped_pngs(reference_dir)
    if not references:
        raise ValueError(f"No FARO-projected high-resolution depth PNGs found in {reference_dir}.")
    frames, synchronization = load_arkitscenes_frames(
        capture_dir, max_timestamp_offset_s=max_timestamp_offset_s
    )
    timestamps = [item[0] for item in references]
    errors: list[np.ndarray] = []
    ranges: list[np.ndarray] = []
    offsets_ms = []
    matched_pairs = []
    used_references: set[Path] = set()
    rejected_matches = 0
    duplicate_reference_matches = 0

    for frame in frames:
        match = _nearest(references, timestamps, frame.timestamp)
        if match is None or abs(match[1]) > max_timestamp_offset_s:
            rejected_matches += 1
            continue
        gt_path, offset = match
        if gt_path in used_references:
            duplicate_reference_matches += 1
            continue
        sensor = cv2.imread(str(frame.depth_path), cv2.IMREAD_UNCHANGED)
        confidence = cv2.imread(str(frame.confidence_path), cv2.IMREAD_UNCHANGED)
        reference = cv2.imread(str(gt_path), cv2.IMREAD_UNCHANGED)
        if sensor is None or confidence is None or reference is None:
            raise ValueError(f"Could not read depth/confidence assets for frame {frame.frame_id}.")
        if sensor.ndim != 2 or confidence.ndim != 2 or reference.ndim != 2:
            raise ValueError("ARKitScenes depth and confidence assets must be single-channel images.")
        if sensor.shape != confidence.shape:
            raise ValueError(f"Sensor depth and confidence raster sizes differ at {frame.frame_id}.")
        if abs((reference.shape[1] / reference.shape[0]) - (sensor.shape[1] / sensor.shape[0])) > 1e-3:
            raise ValueError(f"Reference and sensor depth aspect ratios differ at {frame.frame_id}.")

        # highres_depth is FARO-mesh depth projected into the wide-camera image;
        # resizing uses the normalized raster coordinates for a pixelwise diagnostic.
        reference_small = cv2.resize(
            reference, (sensor.shape[1], sensor.shape[0]), interpolation=cv2.INTER_NEAREST
        )
        sampled_sensor = sensor[::pixel_stride, ::pixel_stride].astype(np.float32) / 1000.0
        sampled_reference = reference_small[::pixel_stride, ::pixel_stride].astype(np.float32) / 1000.0
        sampled_confidence = confidence[::pixel_stride, ::pixel_stride]
        valid = (
            (sampled_confidence > 0)
            & np.isfinite(sampled_sensor)
            & np.isfinite(sampled_reference)
            & (sampled_sensor >= 0.1)
            & (sampled_sensor <= 10.0)
            & (sampled_reference >= 0.1)
            & (sampled_reference <= 10.0)
        )
        if not np.any(valid):
            used_references.add(gt_path)
            continue
        sensor_values = sampled_sensor[valid]
        reference_values = sampled_reference[valid]
        errors.append(np.abs(sensor_values - reference_values))
        ranges.append(reference_values)
        offsets_ms.append(abs(offset) * 1000.0)
        matched_pairs.append({
            "sensor_frame": frame.depth_path.name,
            "reference_frame": gt_path.name,
            "absolute_timestamp_offset_ms": round(abs(offset) * 1000.0, 3),
            "valid_pixels": int(np.count_nonzero(valid)),
        })
        used_references.add(gt_path)

    if not errors:
        raise ValueError(
            "No valid pixel pairs were available. Check timestamps, highres-depth "
            "availability, and the capture's image alignment."
        )
    absolute_error = np.concatenate(errors)
    reference_depth = np.concatenate(ranges)

    def error_stats(mask: np.ndarray) -> dict:
        values = absolute_error[mask]
        if values.size == 0:
            return {"pixels": 0, "mae_m": None, "median_absolute_error_m": None,
                    "within_5cm_percent": None}
        return {
            "pixels": int(values.size),
            "mae_m": round(float(np.mean(values)), 5),
            "median_absolute_error_m": round(float(np.median(values)), 5),
            "within_5cm_percent": round(float(np.mean(values <= 0.05) * 100), 3),
        }

    return {
        "evaluation": "ARKitScenes low-resolution sensor depth vs FARO-projected high-resolution depth",
        "dataset": "ARKitScenes raw",
        "video_id": capture_dir.name,
        "sensor_device_class": "Apple iPad Pro ARKit LiDAR; not an iPhone 15 capture",
        "reference_source": "highres_depth projected from FARO laser-scanner mesh into the wide-camera view",
        "status": "diagnostic_sensor_depth_comparison",
        "official_case_study_plan_gate": "not_scored",
        "comparison_assumptions": [
            "Nearest timestamp highres_depth frame is an appropriate view match to the sparse trajectory/depth frame within the configured tolerance.",
            "Highres and lowres depth share a normalized wide-camera pixel grid; nearest-neighbor resize maps the reference raster to the sensor raster.",
            "Only nonzero ARKit confidence and valid 0.1–10 m depth pairs are scored; FARO reference depth can still contain projection or occlusion error.",
        ],
        "sampling": {
            "max_timestamp_offset_ms": round(max_timestamp_offset_s * 1000, 3),
            "pixel_stride": pixel_stride,
            "matched_frame_pairs": len(matched_pairs),
            "trajectory_join": synchronization,
            "reference_frame_match_offset_ms": {
                "median": round(float(np.median(offsets_ms)), 3),
                "p95": round(float(np.percentile(offsets_ms, 95)), 3),
                "max": round(float(np.max(offsets_ms)), 3),
            },
            "reference_matches_outside_tolerance": rejected_matches,
            "duplicate_reference_matches_skipped": duplicate_reference_matches,
        },
        "depth_error": {
            "valid_pixels": int(absolute_error.size),
            "mae_m": round(float(np.mean(absolute_error)), 5),
            "median_absolute_error_m": round(float(np.median(absolute_error)), 5),
            "p90_absolute_error_m": round(float(np.percentile(absolute_error, 90)), 5),
            "within_2cm_percent": round(float(np.mean(absolute_error <= 0.02) * 100), 3),
            "within_5cm_percent": round(float(np.mean(absolute_error <= 0.05) * 100), 3),
            "within_10cm_percent": round(float(np.mean(absolute_error <= 0.10) * 100), 3),
            "by_reference_range": {
                "0.1_to_1.5m": error_stats((reference_depth >= 0.1) & (reference_depth < 1.5)),
                "1.5_to_3m": error_stats((reference_depth >= 1.5) & (reference_depth < 3.0)),
                "3_to_6m": error_stats((reference_depth >= 3.0) & (reference_depth < 6.0)),
                "6_to_10m": error_stats((reference_depth >= 6.0) & (reference_depth <= 10.0)),
            },
        },
        "matched_pairs": matched_pairs,
        "limitations": [
            "This is a depth-raster comparison, not a room dimension, floor area, opening, or stitched-plan accuracy score.",
            "The scan was captured with an iPad Pro, so it does not validate iPhone image codecs, sensor availability, or walk-in behavior.",
            "The reference is generated from FARO geometry and projected into camera images; its registration and pixel correspondence are dataset-provided assumptions, not a local tape-measured check.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture_dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-timestamp-offset-ms", type=float, default=60.0)
    parser.add_argument("--pixel-stride", type=int, default=2)
    args = parser.parse_args()
    report = evaluate_depth(
        args.capture_dir,
        max_timestamp_offset_s=args.max_timestamp_offset_ms / 1000,
        pixel_stride=args.pixel_stride,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    depth = report["depth_error"]
    print(
        f"Compared {depth['valid_pixels']:,} pixels across "
        f"{report['sampling']['matched_frame_pairs']} frame pairs: "
        f"MAE {depth['mae_m']:.3f} m; within 5 cm "
        f"{depth['within_5cm_percent']:.1f}%"
    )
    print(f"Diagnostic report: {args.output}")
    print("Room dimensions and the official stitched-plan gate remain unscored.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
