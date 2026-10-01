from dataclasses import dataclass
from pathlib import Path
from pipeline.geometry.camera import CameraIntrinsics
from pipeline.geometry.pose import CameraPose


@dataclass
class NormalizedCapture:
    root: Path
    rgb: list
    depth: list
    poses: list[CameraPose]
    intrinsics: CameraIntrinsics | None
    
    
    
def create_empty_capture(root: Path) -> NormalizedCapture:
    return NormalizedCapture(
        root=root,
        rgb=[],
        depth=[],
        poses=[],
        intrinsics=None,
    )