from dataclasses import dataclass
from pathlib import Path


@dataclass
class NormalizedCapture:
    root: Path
    rgb: list
    depth: list
    poses: list
    intrinsics: dict | None
    
    
    
def create_empty_capture(root: Path) -> NormalizedCapture:
    return NormalizedCapture(
        root=root,
        rgb=[],
        depth=[],
        poses=[],
        intrinsics=None,
    )