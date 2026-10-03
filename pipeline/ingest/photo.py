"""Image discovery, decoding, and non-destructive staging for photo captures."""

import shutil
from pathlib import Path

import cv2
from pipeline.ingest.normalized import NormalizedCapture


PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif"}


def discover_photos(folder: Path) -> list[Path]:
    """Return supported still images directly inside a room folder."""
    return sorted(
        path for path in Path(folder).iterdir()
        if path.is_file() and path.suffix.lower() in PHOTO_EXTENSIONS
    )


def read_photo(path: Path):
    """Decode a still image to OpenCV BGR, including iPhone HEIC/HEIF files."""
    path = Path(path)
    if path.suffix.lower() not in {".heic", ".heif"}:
        return cv2.imread(str(path), cv2.IMREAD_COLOR)

    try:
        from PIL import Image, ImageOps
        from pillow_heif import register_heif_opener
    except ImportError as error:
        raise RuntimeError(
            "HEIC/HEIF input requires the project dependencies. Run "
            "python -m pip install -r requirements.txt and retry."
        ) from error

    register_heif_opener()
    import numpy as np

    with Image.open(path) as source:
        oriented = ImageOps.exif_transpose(source).convert("RGB")
        rgb = np.asarray(oriented)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def stage_photo_images(images: list[Path], output_dir: Path) -> list[Path]:
    """Validate and stage source stills; transcode HEIF to COLMAP-readable JPEG."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    staged = []
    for index, source in enumerate(images, start=1):
        decoded = read_photo(source)
        if decoded is None or decoded.size == 0:
            raise ValueError(f"Could not decode photo {source}; export it as JPEG or PNG and retry.")

        suffix = source.suffix.lower()
        output_suffix = ".jpg" if suffix in {".heic", ".heif"} else suffix
        target = output_dir / f"image_{index:04d}{output_suffix}"
        if suffix in {".heic", ".heif"}:
            if not cv2.imwrite(str(target), decoded, [cv2.IMWRITE_JPEG_QUALITY, 95]):
                raise OSError(f"Could not stage decoded HEIC/HEIF photo: {target}")
        else:
            # Keep JPEG/PNG source bytes intact to avoid needless quality loss.
            shutil.copy2(source, target)
        staged.append(target)
    return staged


def load_photos(input_path: Path) -> list:
    photos = []

    for file in discover_photos(input_path):
        image = read_photo(file)
        if image is None:
            raise ValueError(f"Could not decode photo {file}; check the file or re-export it.")
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
    
    

