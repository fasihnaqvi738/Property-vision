from dataclasses import dataclass
from pathlib import Path

from pipeline.ingest.types import CaptureType
from pipeline.ingest.detector import detect_capture_type

@dataclass
class Capture:
    path: Path
    capture_type: CaptureType
    
    
    
def load_capture(input_path: str) -> Capture:
    path = Path(input_path)
    capture_type = detect_capture_type(input_path)

    return Capture(
        path=path,
        capture_type=capture_type,
    )