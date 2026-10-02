from pathlib import Path

from pipeline.ingest.types import CaptureType


def detect_capture_type(input_path: str) -> CaptureType:
    path = Path(input_path)

    # RGB-D datasets contain thousands of PNG depth maps and an RGB video.
    # Identify the bundle before generic image/video extension checks.
    if (
        (path / "depth").is_dir()
        and (path / "confidence").is_dir()
        and (path / "odometry.csv").is_file()
        and (path / "camera_matrix.csv").is_file()
    ):
        return CaptureType.RGBD

    files = [file for file in path.rglob("*") if file.is_file()]

    extensions = {file.suffix.lower() for file in files}

    if extensions & {".jpg", ".jpeg", ".png", ".heic"}:
        return CaptureType.PHOTO

    if extensions & {".mp4", ".mov"}:
        return CaptureType.VIDEO

    if extensions & {".ply", ".las", ".e57"}:
        return CaptureType.LIDAR

    raise ValueError("Could not determine capture type")
