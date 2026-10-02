from pathlib import Path

from pipeline.ingest.types import CaptureType


def detect_capture_type(input_path: str) -> CaptureType:
    path = Path(input_path)

    # Polycam raw LiDAR exports contain synchronized keyframe subdirectories.
    keyframes = path / "keyframes"
    if (
        (keyframes / "depth").is_dir()
        and any((keyframes / name).is_dir() for name in ("cameras", "corrected_cameras"))
        and any((keyframes / name).is_dir() for name in ("images", "corrected_images"))
    ):
        return CaptureType.RGBD

    # RGB-D datasets contain thousands of PNG depth maps and an RGB video.
    # Identify the bundle before generic image/video extension checks.
    if (
        (path / "depth").is_dir()
        and (path / "confidence").is_dir()
        and (path / "rgb.mp4").is_file()
        and (path / "odometry.csv").is_file()
        and (path / "camera_matrix.csv").is_file()
    ):
        return CaptureType.RGBD

    video_extensions = {".mp4", ".mov", ".m4v", ".avi"}
    photo_extensions = {".jpg", ".jpeg", ".png", ".heic"}
    lidar_extensions = {".ply", ".las", ".e57"}
    if path.is_file():
        extension = path.suffix.lower()
        if extension in video_extensions:
            return CaptureType.VIDEO
        if extension in photo_extensions:
            return CaptureType.PHOTO
        if extension in lidar_extensions:
            return CaptureType.LIDAR
        raise ValueError(f"Unsupported capture file type: {path.suffix or '(no extension)'}")

    files = [file for file in path.rglob("*") if file.is_file()]

    extensions = {file.suffix.lower() for file in files}

    if extensions & video_extensions:
        return CaptureType.VIDEO

    if extensions & photo_extensions:
        return CaptureType.PHOTO

    if extensions & lidar_extensions:
        return CaptureType.LIDAR

    raise ValueError("Could not determine capture type")
