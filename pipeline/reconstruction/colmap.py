import shutil
import tempfile
from pathlib import Path

import pycolmap


PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def reconstruct_from_images(
    image_dir: Path,
    output_dir: Path,
    *,
    max_image_size: int | None = None,
    num_threads: int | None = None,
    max_num_features: int | None = None,
    matching_strategy: str = "exhaustive",
    sequential_overlap: int = 10,
) -> list[dict]:
    """Create portable COLMAP text models and PLY point clouds for a photo folder."""
    image_dir = Path(image_dir).expanduser().resolve()
    output_dir = Path(output_dir).expanduser().resolve()

    if not image_dir.is_dir():
        raise FileNotFoundError(f"Photo folder does not exist: {image_dir}")

    image_files = sorted(
        path for path in image_dir.iterdir()
        if path.is_file() and path.suffix.lower() in PHOTO_EXTENSIONS
    )
    if len(image_files) < 2:
        raise ValueError(
            f"Expected at least 2 JPEG or PNG photos directly inside {image_dir}; "
            f"found {len(image_files)}."
        )

    output_dir.mkdir(parents=True, exist_ok=False)
    database_path = output_dir / "database.db"
    sparse_path = output_dir / "sparse"
    sparse_path.mkdir()

    extraction_options = pycolmap.FeatureExtractionOptions()
    matching_options = pycolmap.FeatureMatchingOptions()
    if max_image_size is not None:
        extraction_options.max_image_size = int(max_image_size)
    if num_threads is not None:
        extraction_options.num_threads = int(num_threads)
        matching_options.num_threads = int(num_threads)
    if max_num_features is not None:
        extraction_options.sift.max_num_features = int(max_num_features)

    # COLMAP scans every file in the supplied directory. Stage only supported
    # image inputs so sidecars (for example photo-proxy provenance JSON) are
    # not treated as images and warned about during feature extraction.
    with tempfile.TemporaryDirectory(prefix="property_vision_images_") as staging:
        staged_image_dir = Path(staging)
        for image_path in image_files:
            shutil.copy2(image_path, staged_image_dir / image_path.name)

        pycolmap.extract_features(
            database_path,
            staged_image_dir,
            extraction_options=extraction_options,
        )
        if matching_strategy == "exhaustive":
            pycolmap.match_exhaustive(database_path, matching_options=matching_options)
        elif matching_strategy == "sequential":
            pairing_options = pycolmap.SequentialPairingOptions()
            pairing_options.overlap = int(sequential_overlap)
            pairing_options.quadratic_overlap = False
            if num_threads is not None:
                pairing_options.num_threads = int(num_threads)
            pycolmap.match_sequential(
                database_path,
                matching_options=matching_options,
                pairing_options=pairing_options,
            )
        else:
            raise ValueError("matching_strategy must be 'exhaustive' or 'sequential'.")
        reconstructions = pycolmap.incremental_mapping(
            database_path,
            staged_image_dir,
            sparse_path,
        )

    if not reconstructions:
        raise RuntimeError(
            "COLMAP could not reconstruct this photo set. Use overlapping, "
            "sharp photos with visible textured surfaces, then try again."
        )

    models = []
    models_dir = output_dir / "models"
    models_dir.mkdir()

    for model_id, reconstruction in sorted(reconstructions.items()):
        model_dir = models_dir / str(model_id)
        model_dir.mkdir()
        reconstruction.write_text(model_dir)

        point_cloud_path = model_dir / "points.ply"
        reconstruction.export_PLY(point_cloud_path)
        models.append(
            {
                "model_id": int(model_id),
                "registered_images": len(reconstruction.images),
                "registered_image_names": sorted(
                    str(image.name) for image in reconstruction.images.values()
                ),
                "sparse_points": len(reconstruction.points3D),
                "model_text_dir": str(model_dir),
                "point_cloud_ply": str(point_cloud_path),
                "summary": reconstruction.summary(),
            }
        )

    return models
