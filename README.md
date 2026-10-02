# Property Vision

An early computer-vision prototype for reconstructing a sparse 3D scene from room photos, walkthrough videos, or RGB-D captures.

## Current photo workflow

For one room, use a folder containing at least two overlapping JPEG or PNG images directly inside it. For multiple rooms, use a collection root with one immediate subfolder per room, each containing 2–8 stills. The multi-room input reconstructs each room separately in one command; it does not yet produce the required stitched floor plan. Photos should overlap, be sharp, and show textured surfaces from different viewpoints. A single photo cannot recover 3D geometry.

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

For per-room photo folders, pass their common parent directory:

```powershell
python main.py "C:\captures\property-photos"
```

The root must contain at least two immediate room folders, for example `R01\`, `R02\`, and `C01\`; each must contain 2–8 JPEG/PNG stills directly inside it. One result includes the independent reconstruction for each room and a joint COLMAP reconstruction attempt across all images, with room-folder membership reported for connected models. The joint sparse model is only a cross-room matching diagnostic: scale, room placement, dimensions, adjacency, overlap checks, and the homeowner-ready stitch remain unavailable.

Photo reconstruction limits COLMAP to four CPU threads to keep feature extraction more predictable on high-resolution images. The setting is recorded under `reconstruction.summary.reconstruction_settings` in each result.

## Walkthrough video workflow

Pass a single video file directly, or a property folder containing one walkthrough video per room:

```powershell
python main.py "captures\walkthrough.mp4"
python main.py "captures\property_videos"
```

For a multi-room folder, put one clip per room directly in the folder or one level down in folders named by room ID. The command returns one JSON result with separate sparse reconstructions for each clip; it does not align camera poses between clips or stitch a property plan. Each clip is sampled approximately four frames per second (up to 160 frames), saves selected frames and a contact sheet, then sends those frames through COLMAP sparse reconstruction with sequential matching. If the cap is reached, samples are spread across the complete clip and the result reports the effective rate and clip coverage. The result uses the shared JSON envelope with `capture.tier` set to `video`. This is sparse monocular reconstruction with arbitrary scale; it does not yet produce dimensioned rooms, classified openings, drift correction, or calibrated uncertainty.

Video results report `video_reconstruction_quality` in the result summary: sampled-frame count, model count, largest-model coverage, and per-model registration memberships. Multiple models trigger a limitation warning because the selected primary point cloud may cover only part of the walkthrough.

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

An extracted Polycam LiDAR Raw Data folder is also accepted directly (it must contain `keyframes/depth/`, matching RGB images, and camera JSON files):

```powershell
python main.py "C:\captures\polycam-room"
```

The Polycam adapter joins images, depth, confidence, and camera poses by shared timestamp, prefers corrected image/pose folders when both are present, interprets documented depth values as millimeters, converts ARKit camera axes for back-projection, uses the documented Y-up world axis for floor analysis, and excludes low-confidence pixels. The input ZIP itself must be extracted first. No actual Polycam raw capture is present in this repository, so this route still needs a real-device run before it is considered validated.

To create a drift-handling ablation from the same extracted capture, run it twice:

```powershell
python main.py "C:\captures\polycam-room" --pose-mode raw
python main.py "C:\captures\polycam-room" --pose-mode optimized
python pipeline\evaluation\drift_ablation.py --raw "outputs\<raw-run>\result.json" --optimized "outputs\<optimized-run>\result.json"
```

The evaluator requires results from the same capture path and reports diagnostic changes in observed floor coverage, pose translation spans, wall alignment, and geometry candidate counts. It does not establish accuracy or that optimized poses are better; that requires independent measured ground truth. The default report is written beside the optimized run as `drift_ablation.json`.

This creates a colored `rgbd_point_cloud.ply`, `floor_return_preview.png`, `wall_plane_candidates.png`, and `wall_boundary_diagnostic.png`, and writes `result.json` in a timestamped output folder. The output records `reconstruction.summary.processing_runtime_seconds`, measured from capture type detection through reconstruction and artifact generation (excluding result JSON writing). The export samples every tenth depth frame and every fourth pixel. It matches RGB presentation timestamps to the depth odometry timestamps, and records the time offsets and alignment assumptions in the manifest. The floor preview outlines the largest connected area of observed floor returns and records its polygon and observed-cell area. The wall pass suppresses overlapping near-coplanar detections, compares candidate spans with nearby floor-outline support, and reports snapped endpoint cycles, line-intersection face hypotheses, provisional edge lengths, interior angles, and nearby unclosed endpoint gaps. It also screens internal wall voids and boundary gaps for possible openings, while leaving every finding unverified. The geometry review checks whether each face is simple, supported, and room-shaped under provisional thresholds. These are still diagnostics, not room labels, identified doors/windows, or calibrated room measurements: observed floor coverage is not the room footprint, an aligned candidate is not a verified wall, and a closed face is not proof of a room. Provisional edge lengths and areas have no calibrated confidence intervals. The pipeline treats depth values as millimeters, odometry poses as camera-to-world transforms, and the least-varying camera-motion axis as vertical; all need validation against capture documentation and ground truth. It does not yet create an accepted floor plan or calibrated room measurements.

Any line-intersection faces are also copied to `property_plan.boundary_hypotheses` in `result.json` with their vertices, candidate area, edge lengths, supporting wall IDs, and explicit uncalibrated status. `property_plan.rooms` remains empty until a candidate is independently validated and accepted; these hypotheses are not a rendered or measured room plan.

Each RGB-D run also writes `geometry_review.geojson`, containing the observed floor-coverage outline, projected wall spans, candidate face polygons, and unclassified boundary-gap review targets, plus a vector `geometry_review.svg` sheet labeling the candidate area, side lengths, and open gaps. Gap features have a blank `review_label` field for manual annotation; they are not opening detections. These files use a capture-local coordinate frame with metres assumed and are intended for review, not as a survey-ready floor plan.

Photo, video, and RGB-D runs share the versioned output envelope defined in `schemas/property_capture_result.schema.json`. Every newly generated `result.json` is checked against that schema before it is written. Existing output folders can be checked in bulk:

```powershell
python -m pipeline.validation outputs
python -m pipeline.validation outputs\some_run\result.json
```

Until room extraction and calibration are implemented, unsupported plan and measurement fields are explicitly marked unavailable. The requirement-by-requirement status is tracked in `docs/compliance_matrix.md`.

The repeatable field procedure for matching room IDs across photo, video, LiDAR, staged-damage, and ground-truth captures is in [`docs/capture_protocol.md`](docs/capture_protocol.md). Extracted Polycam raw-data folders are supported; the ZIP itself must be extracted before running the pipeline.

## Ground-truth benchmark scoring

`pipeline/evaluation/benchmark.py` scores saved `result.json` files against a manually measured manifest. Follow [`benchmark/README.md`](benchmark/README.md), then copy `benchmark/ground_truth.template.json` to `benchmark/ground_truth.json`; the template has the required three-room-plus-connector structure but still needs measured values and capture runs. Record room areas, ceiling heights, wall lengths, opening widths, multi-room footprint/adjacency, and each run's result path. Add reviewed ID correspondences in each run's `wall_matches` and `opening_matches`. Record missed openings with a `null` prediction ID and every phantom opening in `phantom_opening_prediction_ids` so both count as detection errors. Reuse a `repeat_group` for captures of the same room and tier.

Run it with:

```powershell
python pipeline\evaluation\benchmark.py benchmark\ground_truth.json
```

The report scores opening width within 2 cm on at least 85% (including misses/phantoms), ceiling height within 1.5 cm, repeated ceiling spread within 1 cm, repeated wall spread within the larger of 1 cm or 0.5% of ground-truth length, photo/video wall lengths within 8%/3%, photo stitched footprint within 8% with ground truth inside its reported interval plus correct adjacency and no overlaps, and video whole-property footprint within 3%. It reports empirical interval coverage by tier and metric. It does not score the incumbent comparison, runtime, drift ablation, or benchmark-set composition; those require their own evidence.

## Current limitations

- COLMAP's monocular reconstruction does not establish metric scale by itself.
- Sparse points and camera poses are not a floor plan. Multi-room photo/video inputs are accepted, but room placement, accepted dimensions, openings, adjacency, and damage interpretation are unavailable.
- The full case-study contract still needs three-tier capture, multi-room stitching, a real-data-validated drift ablation, ground-truthed benchmarks, calibrated intervals, the incumbent comparison, and the fix loop.
