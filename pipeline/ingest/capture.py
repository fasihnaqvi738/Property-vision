from dataclasses import dataclass
from pathlib import Path
from pipeline.ingest.types import CaptureType
from pipeline.ingest.detector import detect_capture_type
from pipeline.ingest.metadata import CaptureMetadata
from pipeline.ingest.tiers import CaptureTier
from pipeline.ingest.normalized import NormalizedCapture

@dataclass
class Capture:
    path: Path
    capture_type: CaptureType
    photos: list
    metadata: CaptureMetadata
    normalized: NormalizedCapture | None
    
    
def load_capture(input_path: str) -> Capture:
    path = Path(input_path)
    capture_type = detect_capture_type(input_path)

    # Keep capture loading lightweight. iPhone stills can be 48 MP; decode and
    # validate them one at a time during staging instead of retaining every
    # full-resolution frame in memory before reconstruction starts.
    photos = []
    normalized = None

    metadata = CaptureMetadata(
        device="unknown",
        tier=CaptureTier(capture_type.value),
    )   

    return Capture(
        path=path,
        capture_type=capture_type,
        photos=photos,
        metadata=metadata,
        normalized=normalized
    )
    

