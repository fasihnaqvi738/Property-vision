import json
from datetime import datetime, timezone
from pathlib import Path

from pipeline.ingest.capture import load_capture
from pipeline.ingest.types import CaptureType
from pipeline.ingest.rgbd import reconstruct_rgbd
from pipeline.reconstruction.colmap import reconstruct_from_images


def run_pipeline(input_path: str, output_root: str = "outputs") -> Path:
    capture = load_capture(input_path)
    if capture.capture_type is CaptureType.RGBD:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        run_dir = Path(output_root) / f"{capture.path.name}_{timestamp}"
        result = reconstruct_rgbd(capture.path, run_dir)
        return run_dir / "result.json"

    if capture.capture_type is not CaptureType.PHOTO:
        raise NotImplementedError(
            f"The photo reconstruction workflow does not support "
            f"{capture.capture_type.value} captures yet."
        )

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

    result = {
        "format_version": 1,
        "capture": {
            "path": str(capture.path.resolve()),
            "tier": capture.metadata.tier.value,
            "photo_count": len(photo_files),
            "photos": [path.name for path in photo_files],
        },
        "reconstruction": {
            "engine": "COLMAP",
            "status": "success",
            "models": models,
            "scale": "arbitrary",
            "limitations": [
                "Monocular photo reconstruction has no metric scale without a known dimension or depth sensor.",
                "This output is a sparse 3D reconstruction, not a measured floor plan.",
            ],
        },
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    result_path = run_dir / "result.json"
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result_path
