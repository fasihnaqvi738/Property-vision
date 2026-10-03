"""Download one small, reproducible ARKitScenes RGB-D/reference-depth sample.

Dataset media is written under captures/ (ignored by Git). This script does not
redistribute the data; it records URLs and SHA-256 hashes for local provenance.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import shutil
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath


BASE_URL = "https://docs-assets.developer.apple.com/ml-research/datasets/arkitscenes/v1"
DEFAULT_VIDEO_ID = "42445884"
ASSETS = (
    "lowres_wide.zip",
    "lowres_depth.zip",
    "confidence.zip",
    "lowres_wide_intrinsics.zip",
    "lowres_wide.traj",
    "highres_depth.zip",
)


def _read_metadata(video_id: str) -> dict[str, str]:
    request = urllib.request.Request(
        f"{BASE_URL}/raw/metadata.csv",
        headers={"User-Agent": "PropertyVision-public-dataset-evaluation/1.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        rows = csv.DictReader(io.TextIOWrapper(response, encoding="utf-8-sig"))
        row = next((item for item in rows if item["video_id"] == video_id), None)
    if row is None:
        raise ValueError(f"ARKitScenes raw metadata has no video ID {video_id}.")
    if row["is_in_upsampling"].lower() != "true":
        raise ValueError(
            f"Video {video_id} has no highres_depth reference asset; choose a video "
            "whose metadata has is_in_upsampling=True."
        )
    return row


def _download(url: str, destination: Path) -> dict[str, int | str]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    digest = hashlib.sha256()
    byte_count = 0
    request = urllib.request.Request(url, headers={"User-Agent": "PropertyVision-public-dataset-evaluation/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=90) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                digest.update(chunk)
                byte_count += len(chunk)
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return {"url": url, "bytes": byte_count, "sha256": digest.hexdigest()}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_safely(archive_path: Path, destination: Path) -> int:
    root = destination.resolve()
    extracted = 0
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            relative = PurePosixPath(member.filename)
            if relative.is_absolute() or any(part in {"..", ""} for part in relative.parts):
                raise ValueError(f"Unsafe path in dataset archive: {member.filename}")
            target = (root / Path(*relative.parts)).resolve()
            try:
                target.relative_to(root)
            except ValueError as error:
                raise ValueError(f"Unsafe path in dataset archive: {member.filename}") from error
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            extracted += 1
    return extracted


def download_sample(video_id: str, output_dir: Path) -> Path:
    metadata = _read_metadata(video_id)
    split = metadata["fold"]
    capture_dir = Path(output_dir) / "raw" / split / video_id
    archive_dir = Path(output_dir) / "_archives" / video_id
    capture_dir.mkdir(parents=True, exist_ok=True)
    downloaded = {}
    extracted_files = {}

    for asset in ASSETS:
        url = f"{BASE_URL}/raw/{split}/{video_id}/{asset}"
        zipped = asset.endswith(".zip")
        destination = (archive_dir if zipped else capture_dir) / asset
        archived_copy = archive_dir / asset
        if not zipped and not destination.is_file() and archived_copy.is_file():
            shutil.copy2(archived_copy, destination)
        if not destination.is_file():
            downloaded[asset] = _download(url, destination)
        else:
            downloaded[asset] = {
                "url": url,
                "bytes": destination.stat().st_size,
                "sha256": _sha256_file(destination),
                "reused_local_archive": True,
            }
        if zipped:
            subdirectory = asset.removesuffix(".zip")
            extracted_dir = capture_dir / subdirectory
            with zipfile.ZipFile(destination) as archive:
                expected_files = sum(not member.is_dir() for member in archive.infolist())
            actual_files = (
                sum(1 for path in extracted_dir.rglob("*") if path.is_file())
                if extracted_dir.is_dir()
                else 0
            )
            if actual_files < expected_files:
                extracted_files[subdirectory] = _extract_safely(destination, capture_dir)
            else:
                extracted_files[subdirectory] = actual_files

    manifest = {
        "dataset": "ARKitScenes raw",
        "video_id": video_id,
        "visit_id": metadata["visit_id"],
        "split": split,
        "capture_device_class": "Apple iPad Pro with ARKit LiDAR (not iPhone 15 test evidence)",
        "source": "https://github.com/apple/ARKitScenes",
        "download_base": BASE_URL,
        "license_reference": "https://github.com/apple/ARKitScenes/blob/main/LICENSE",
        "citation": "Baruch et al., ARKitScenes, NeurIPS Datasets and Benchmarks 2021, https://openreview.net/forum?id=tjZjv_qh_CE",
        "redistribute_dataset_media": False,
        "downloaded_assets": downloaded,
        "extracted_file_counts": extracted_files,
        "capture_folder": str(capture_dir),
    }
    manifest_path = capture_dir / "property_vision_dataset_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video-id", default=DEFAULT_VIDEO_ID)
    parser.add_argument("--output-dir", type=Path, default=Path("captures/_public_arkitscenes"))
    args = parser.parse_args()
    manifest = download_sample(args.video_id, args.output_dir)
    details = json.loads(manifest.read_text(encoding="utf-8"))
    print(f"Downloaded ARKitScenes {details['video_id']} ({details['visit_id']})")
    print(f"Capture folder: {manifest.parent}")
    print(f"Manifest: {manifest}")
    print("Dataset media is local and must not be committed or redistributed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
