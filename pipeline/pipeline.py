import json
from datetime import datetime, timezone
from pathlib import Path

from pipeline.ingest.capture import load_capture
from pipeline.ingest.types import CaptureType
from pipeline.ingest.rgbd import reconstruct_rgbd
from pipeline.ingest.video import sample_walkthrough_video
from pipeline.results import build_result
from pipeline.validation import validate_result


def _write_result(result: dict, result_path: Path) -> Path:
    """Validate every tier's output before persisting the shared contract."""
    validate_result(result)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result_path


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
            debug_views=[
                str(run_dir / summary[key]["preview"])
                for key in ("floor_return_analysis", "wall_plane_analysis")
                if summary.get(key, {}).get("status") == "diagnostic_only"
            ] + (
                [str(run_dir / summary["wall_plane_analysis"]["boundary_preview"])]
                if summary.get("wall_plane_analysis", {}).get("boundary_preview")
                else []
            ),
        )
        return _write_result(result, run_dir / "result.json")

    if capture.capture_type is CaptureType.VIDEO:
        video_extensions = {".mp4", ".mov", ".m4v", ".avi"}
        if capture.path.is_file():
            video_path = capture.path
        else:
            videos = sorted(
                path for path in capture.path.rglob("*")
                if path.is_file() and path.suffix.lower() in video_extensions
            )
            if len(videos) != 1:
                raise ValueError(
                    f"Expected exactly one walkthrough video in {capture.path}; found {len(videos)}. "
                    "Pass the specific video file when a folder contains multiple videos."
                )
            video_path = videos[0]

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        run_dir = Path(output_root) / f"{capture.path.stem}_{timestamp}"
        run_dir.mkdir(parents=True, exist_ok=False)
        sampling = sample_walkthrough_video(video_path, run_dir)
        from pipeline.reconstruction.colmap import reconstruct_from_images

        reconstruction_settings = {
            "max_image_size": 1280,
            "num_threads": 4,
            "max_num_features": 4096,
            "matching_strategy": "sequential",
            "sequential_overlap": 30,
        }
        models = reconstruct_from_images(
            run_dir / sampling["frame_directory"],
            run_dir / "reconstruction",
            **reconstruction_settings,
        )
        primary_model = max(
            models,
            key=lambda model: (model["registered_images"], model["sparse_points"]),
            default=None,
        )
        limitations = [
            "Walkthrough frames are sampled from video and reconstructed as a sparse monocular image set.",
            "The reconstruction has arbitrary scale and does not yield verified room dimensions or openings.",
            "Video motion, rolling shutter, exposure changes, and repeated viewpoints can reduce image matching quality.",
            "Sampling and bundle adjustment do not implement a validated drift correction or loop-closure ablation.",
        ]
        result = build_result(
            capture_id=capture.path.stem,
            tier="video",
            source_format="walkthrough_video",
            device=capture.metadata.device,
            input_files=[str(video_path.name)],
            reconstruction_method="OpenCV video frame sampling followed by COLMAP incremental mapping",
            reconstruction_summary={
                "capture_type": "video",
                "sampling": sampling,
                "models": models,
                "primary_model_id": primary_model["model_id"] if primary_model else None,
                "scale": "arbitrary",
                "reconstruction_settings": reconstruction_settings,
            },
            point_cloud=primary_model["point_cloud_ply"] if primary_model else None,
            limitations=limitations,
            raw_capture=[str(video_path.resolve())],
            debug_views=[str(run_dir / sampling["contact_sheet"])],
        )
        return _write_result(result, run_dir / "result.json")

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
    primary_model = max(
        models,
        key=lambda model: (model["registered_images"], model["sparse_points"]),
        default=None,
    )

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
        point_cloud=primary_model["point_cloud_ply"] if primary_model else None,
        limitations=limitations,
        raw_capture=[str(capture.path.resolve())],
    )
    return _write_result(result, run_dir / "result.json")
