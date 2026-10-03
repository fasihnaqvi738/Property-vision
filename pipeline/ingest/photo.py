"""Image discovery, decoding, and non-destructive staging for photo captures."""

import shutil
from pathlib import Path

import cv2
from pipeline.ingest.normalized import NormalizedCapture


PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif"}
EXIF_MAKE_TAG = 271
EXIF_MODEL_TAG = 272
EXIF_ORIENTATION_TAG = 274


def discover_photos(folder: Path) -> list[Path]:
    """Return supported still images directly inside a room folder."""
    return sorted(
        path for path in Path(folder).iterdir()
        if path.is_file() and path.suffix.lower() in PHOTO_EXTENSIONS
    )


def _orient_pillow_image(image, image_ops):
    """Apply Pillow and pillow-heif orientation metadata to decoded pixels."""
    from PIL import Image

    # pillow-heif resets the EXIF tag to 1 on open and preserves the original
    # value in info, so ImageOps.exif_transpose alone would miss HEIF rotation.
    original_orientation = image.info.get("original_orientation")
    if original_orientation is None:
        return image_ops.exif_transpose(image)
    try:
        orientation = int(original_orientation)
    except (TypeError, ValueError):
        return image_ops.exif_transpose(image)
    operations = {
        2: Image.Transpose.FLIP_LEFT_RIGHT,
        3: Image.Transpose.ROTATE_180,
        4: Image.Transpose.FLIP_TOP_BOTTOM,
        5: Image.Transpose.TRANSPOSE,
        6: Image.Transpose.ROTATE_270,
        7: Image.Transpose.TRANSVERSE,
        8: Image.Transpose.ROTATE_90,
    }
    operation = operations.get(orientation)
    return image.transpose(operation) if operation is not None else image.copy()


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
        oriented = _orient_pillow_image(source, ImageOps).convert("RGB")
        rgb = np.asarray(oriented)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def infer_photo_device(images: list[Path]) -> str | None:
    """Read camera make/model only; do not infer OS or capture-app versions."""
    try:
        from PIL import Image
    except ImportError:
        return None

    identities = set()
    for path in images:
        path = Path(path)
        try:
            if path.suffix.lower() in {".heic", ".heif"}:
                from pillow_heif import register_heif_opener

                register_heif_opener()
            with Image.open(path) as source:
                exif = source.getexif()
                make = str(exif.get(EXIF_MAKE_TAG, "")).strip().replace("\x00", " ")
                model = str(exif.get(EXIF_MODEL_TAG, "")).strip().replace("\x00", " ")
        except (ImportError, OSError, ValueError):
            continue
        make = " ".join(make.split())
        model = " ".join(model.split())
        if not model and not make:
            continue
        identity = model if not make or make.casefold() in model.casefold() else f"{make} {model}".strip()
        identities.add(identity)

    if not identities:
        return None
    if len(identities) == 1:
        camera = next(iter(identities))
        return f"{camera} (EXIF; OS and capture app unknown)"
    return f"Mixed camera models in photo EXIF: {'; '.join(sorted(identities))}"


def stage_photo_images(images: list[Path], output_dir: Path) -> list[Path]:
    """Validate and stage source stills; transcode HEIF to COLMAP-readable JPEG."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    staged = []
    for index, source in enumerate(images, start=1):
        suffix = source.suffix.lower()
        output_suffix = ".jpg" if suffix in {".heic", ".heif"} else suffix
        target = output_dir / f"image_{index:04d}{output_suffix}"
        if suffix in {".heic", ".heif"}:
            from PIL import Image, ImageOps
            from pillow_heif import register_heif_opener

            register_heif_opener()
            with Image.open(source) as original:
                # Apply source orientation before editing its EXIF view.
                oriented = _orient_pillow_image(original, ImageOps).convert("RGB")
                exif = original.getexif()
                # Orientation is applied to the pixels below. Keep camera and
                # focal-length EXIF useful to COLMAP without preserving location.
                exif.pop(34853, None)  # GPSInfo may reveal the home address.
                exif.pop(EXIF_ORIENTATION_TAG, None)
                if oriented.width <= 0 or oriented.height <= 0:
                    raise ValueError(f"Could not decode photo {source}; export it as JPEG or PNG and retry.")
                exif[EXIF_ORIENTATION_TAG] = 1
                oriented.save(
                    target, format="JPEG", quality=95, exif=exif.tobytes()
                )
        else:
            decoded = read_photo(source)
            if decoded is None or decoded.size == 0:
                raise ValueError(f"Could not decode photo {source}; export it as JPEG or PNG and retry.")
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
