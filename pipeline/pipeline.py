import json
from datetime import datetime, timezone
from pathlib import Path

from pipeline.ingest.capture import load_capture
from pipeline.ingest.types import CaptureType
from pipeline.ingest.rgbd import reconstruct_rgbd
from pipeline.results import build_result


def run_pipeline(input_path: str, output_root: str = "outputs") -> Path:
    capture = load_capture(input_path)
    if capture.capture_type is CaptureType.RGBD:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        run_dir = Path(output_root) / f"{capture.path.name}_{timestamp}"
        summary = reconstruct_rgbd(capture.path, run_dir)
        result = build_result(
            capture_id=capture.path.name,
            tier="lidar",
            source_format="rgbd_bundle",
            device=capture.metadata.device,
            input_files=[
                "rgb.mp4",
                "camera_matrix.csv",
                "odometry.csv",
                "depth/*.png",
                "confidence/*.png",
            ],
            reconstruction_method="RGB-D depth back-projection with supplied odometry poses",
            reconstruction_summary=summary,
            point_cloud=str(run_dir / "rgbd_point_cloud.ply"),
            limitations=summary["limitations"],
            raw_capture=[str(capture.path.resolve())],
        )
        result_path = run_dir / "result.json"
        result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result_path

    if capture.capture_type is not CaptureType.PHOTO:
        raise NotImplementedError(
            f"The photo reconstruction workflow does not support "
            f"{capture.capture_type.value} captures yet."
        )

    from pipeline.reconstruction.colmap import reconstruct_from_images

    photo_files = sorted(
        path for path in capture.path.iterdir()
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )
    if not photo_files:
        raise ValueError(
            f"No JPEG or PNG photos found directly inside {capture.path}."
        )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = Path(output_root) / f"{capture.path.name}_{timestamp}"
    models = reconstruct_from_images(capture.path, run_dir / "reconstruction")

    limitations = [
        "Monocular photo reconstruction has no metric scale without a known dimension or depth sensor.",
        "This output is a sparse 3D reconstruction, not a measured floor plan.",
    ]
    result = build_result(
        capture_id=capture.path.name,
        tier="photo",
        source_format="room_photo_folder",
        device=capture.metadata.device,
        input_files=[path.name for path in photo_files],
        reconstruction_method="COLMAP incremental mapping",
        reconstruction_summary={"models": models, "scale": "arbitrary"},
        point_cloud=models[0]["point_cloud_ply"] if models else None,
        limitations=limitations,
        raw_capture=[str(capture.path.resolve())],
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    result_path = run_dir / "result.json"
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result_path
