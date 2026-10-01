from pathlib import Path
from pipeline.ingest.normalized import NormalizedCapture, create_empty_capture
import cv2


def load_photos(input_path: Path) -> list:
    photos = []

    for file in sorted(input_path.iterdir()):
        if file.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            image = cv2.imread(str(file))

            if image is not None:
                photos.append(image)

    return photos


def normalize_photos(input_path: Path, photos: list) -> NormalizedCapture:
    return NormalizedCapture(
        root=input_path,
        rgb=photos,
        depth=[],
        poses=[],
        intrinsics=None,
    )
    
    

