from pathlib import Path

from pipeline.ingest.types import CaptureType


def detect_capture_type(input_path: str) -> CaptureType:
    path = Path(input_path)

    files = [file for file in path.rglob("*") if file.is_file()]

    extensions = {file.suffix.lower() for file in files}

    if extensions & {".jpg", ".jpeg", ".png", ".heic"}:
        return CaptureType.PHOTO

    if extensions & {".mp4", ".mov"}:
        return CaptureType.VIDEO

    if extensions & {".ply", ".las", ".e57"}:
        return CaptureType.LIDAR

    raise ValueError("Could not determine capture type")