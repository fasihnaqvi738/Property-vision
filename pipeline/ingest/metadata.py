from dataclasses import dataclass

from pipeline.ingest.tiers import CaptureTier


@dataclass
class CaptureMetadata:
    device: str
    tier: CaptureTier