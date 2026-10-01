from dataclasses import dataclass
from pathlib import Path

from pipeline.ingest.types import CaptureType
from pipeline.ingest.detector import detect_capture_type
from pipeline.ingest.capture import load_capture


def main():
    capture = load_capture("captures/test_photo")

    print("Path:", capture.path)
    print("Type:", capture.capture_type.value)
    print("Capture ready")

if __name__ == "__main__":
    main()