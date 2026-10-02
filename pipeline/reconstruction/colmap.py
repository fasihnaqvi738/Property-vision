from pathlib import Path

import pycolmap


PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def reconstruct_from_images(image_dir: Path, output_dir: Path) -> list[dict]:
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

    pycolmap.extract_features(database_path, image_dir)
    pycolmap.match_exhaustive(database_path)
    reconstructions = pycolmap.incremental_mapping(
        database_path,
        image_dir,
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
                "sparse_points": len(reconstruction.points3D),
                "model_text_dir": str(model_dir),
                "point_cloud_ply": str(point_cloud_path),
                "summary": reconstruction.summary(),
            }
        )

    return models
