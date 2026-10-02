# Property Vision

An early computer-vision prototype for reconstructing a sparse 3D scene from room photos, walkthrough videos, or RGB-D captures.

## Current photo workflow

Use a folder containing at least two overlapping JPEG or PNG images of the same room. Keep the images directly in that folder (not in subfolders). The photos should overlap, be sharp, and show textured surfaces from different viewpoints. A single photo cannot recover 3D geometry.

### Setup (Windows PowerShell)

Use 64-bit Python 3.13, then run these commands from the repository root:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Run one capture

```powershell
python main.py "captures\photo_room"
```

Pass any other room-photo folder as the first argument. To store results elsewhere, pass `--output-dir`:

```powershell
python main.py "C:\captures\living-room" --output-dir "C:\results"
```

## Walkthrough video workflow

Pass a single video file directly, or a folder containing exactly one video:

```powershell
python main.py "captures\walkthrough.mp4"
```

The prototype samples approximately four frames per second (up to 160 frames), saves the selected frames and a contact sheet, then sends those frames through COLMAP sparse reconstruction with sequential matching. The result uses the shared JSON envelope with `capture.tier` set to `video`. This is a sparse monocular reconstruction with arbitrary scale; it does not yet produce dimensioned rooms, classified openings, drift correction, or calibrated uncertainty.

Each run creates a timestamped folder under `outputs` (or the selected output directory) containing:

- `result.json`: input file list, COLMAP summary, model counts, output paths, and scale limitations.
- `reconstruction\models\<id>\`: portable COLMAP text model (`cameras.txt`, `images.txt`, and `points3D.txt`).
- `reconstruction\models\<id>\points.ply`: sparse point cloud, viewable in CloudCompare, MeshLab, or another PLY viewer.
- `reconstruction\database.db`: COLMAP feature and match database used for the run.
- For video runs: sampled `video_frames\`, `video_sample_contact_sheet.png`, and `video_sampling.json`.

Photo and video models have arbitrary scale. These workflows do not yet produce a dimensioned room plan or report walls, openings, room area, damage, or confidence intervals. Standalone point-cloud and HEIC ingestion are not implemented. Each run writes to a new folder, so previous results are retained.

## RGB-D capture workflow

The supplied RGB-D bundle can be passed directly as the capture folder. It must contain `depth/`, `confidence/`, `rgb.mp4`, `camera_matrix.csv`, and `odometry.csv`:

```powershell
python main.py "captures\c00a170fe1"
```

This creates a colored `rgbd_point_cloud.ply`, `floor_return_preview.png`, `wall_plane_candidates.png`, and `wall_boundary_diagnostic.png`, and writes `result.json` in a timestamped output folder. The export samples every tenth depth frame and every fourth pixel. It matches RGB presentation timestamps to the depth odometry timestamps, and records the time offsets and alignment assumptions in the manifest. The floor preview outlines the largest connected area of observed floor returns and records its polygon and observed-cell area. The wall pass suppresses overlapping near-coplanar detections, compares candidate spans with nearby floor-outline support, and reports snapped endpoint cycles, line-intersection face hypotheses, provisional edge lengths, interior angles, and nearby unclosed endpoint gaps. It also screens internal wall voids and boundary gaps for possible openings, while leaving every finding unverified. The geometry review checks whether each face is simple, supported, and room-shaped under provisional thresholds. These are still diagnostics, not room labels, identified doors/windows, or calibrated room measurements: observed floor coverage is not the room footprint, an aligned candidate is not a verified wall, and a closed face is not proof of a room. Provisional edge lengths and areas have no calibrated confidence intervals. The pipeline treats depth values as millimeters, odometry poses as camera-to-world transforms, and the least-varying camera-motion axis as vertical; all need validation against capture documentation and ground truth. It does not yet create an accepted floor plan or calibrated room measurements.

Any line-intersection faces are also copied to `property_plan.boundary_hypotheses` in `result.json` with their vertices, candidate area, edge lengths, supporting wall IDs, and explicit uncalibrated status. `property_plan.rooms` remains empty until a candidate is independently validated and accepted; these hypotheses are not a rendered or measured room plan.

Each RGB-D run also writes `geometry_review.geojson`, containing the observed floor-coverage outline, projected wall spans, candidate face polygons, and unclassified boundary-gap review targets. Gap features have a blank `review_label` field for manual annotation; they are not opening detections. The file uses a capture-local coordinate frame with metres assumed and is intended for GIS review, not as a survey-ready floor plan.

Photo, video, and RGB-D runs share the versioned output envelope defined in `schemas/property_capture_result.schema.json`. Every newly generated `result.json` is checked against that schema before it is written. Existing output folders can be checked in bulk:

```powershell
python -m pipeline.validation outputs
python -m pipeline.validation outputs\some_run\result.json
```

Until room extraction and calibration are implemented, unsupported plan and measurement fields are explicitly marked unavailable. The requirement-by-requirement status is tracked in `docs/compliance_matrix.md`.

The repeatable field procedure for matching room IDs across photo, video, LiDAR, staged-damage, and ground-truth captures is in [`docs/capture_protocol.md`](docs/capture_protocol.md). Polycam raw-data ZIPs described there need an ingestion adapter before this pipeline can process them.

## Ground-truth benchmark scoring

`pipeline/evaluation/benchmark.py` scores saved `result.json` files against a manually measured manifest. Start from `benchmark/ground_truth.template.json`; record room areas, ceiling heights, wall lengths, opening widths, multi-room footprint/adjacency, and each run's result path. Add reviewed ID correspondences in each run's `wall_matches` and `opening_matches`. Record missed openings with a `null` prediction ID and every phantom opening in `phantom_opening_prediction_ids` so both count as detection errors. Reuse a `repeat_group` for captures of the same room and tier.

Run it with:

```powershell
python pipeline\evaluation\benchmark.py benchmark\ground_truth.json
```

The report scores opening width within 2 cm on at least 85% (including misses/phantoms), ceiling height within 1.5 cm, repeated ceiling spread within 1 cm, repeated wall spread within the larger of 1 cm or 0.5% of ground-truth length, photo/video wall lengths within 8%/3%, and photo stitched footprint within 8% with ground truth inside its reported interval, correct adjacency, and no overlaps. It reports empirical interval coverage by tier and metric. It does not score the incumbent comparison, runtime, drift ablation, or benchmark-set composition; those require their own evidence.

## Current limitations

- COLMAP's monocular reconstruction does not establish metric scale by itself.
- Sparse points and camera poses are not a floor plan; there is no wall, opening, room-adjacency, or damage interpretation yet.
- The full case-study contract still needs three-tier capture, multi-room stitching, drift handling, ground-truthed benchmarks, calibrated intervals, the incumbent comparison, and the fix loop.
