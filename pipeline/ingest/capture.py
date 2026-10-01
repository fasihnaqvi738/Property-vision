from dataclasses import dataclass
from pathlib import Path
from pipeline.ingest.photo import load_photos
from pipeline.ingest.types import CaptureType
from pipeline.ingest.detector import detect_capture_type
from pipeline.ingest.metadata import CaptureMetadata
from pipeline.ingest.tiers import CaptureTier

@dataclass
class Capture:
    path: Path
    capture_type: CaptureType
    photos: list
    metadata: CaptureMetadata
    
    
def load_capture(input_path: str) -> Capture:
    path = Path(input_path)
    capture_type = detect_capture_type(input_path)

    photos = []

    if capture_type == CaptureType.PHOTO:
        photos = load_photos(path)

    metadata = CaptureMetadata(
        device="unknown",
        tier=CaptureTier(capture_type.value),
    )   

    return Capture(
        path=path,
        capture_type=capture_type,
        photos=photos,
        metadata=metadata
    )
    

