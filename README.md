# Property Vision

Property Vision processes room photos, walkthrough videos, and RGB-D/LiDAR captures into reconstruction artifacts, scan-derived plan candidates, and optional damage-assessment sidecars.

For a simple Windows setup and capture handoff, start with the [one-page capture protocol](docs/one_page_capture_protocol.md).

## Start here

1. Complete [Windows setup](#setup-windows-powershell) once from the repository folder.
2. Prepare and label the capture folders using the [one-page capture protocol](docs/one_page_capture_protocol.md). Use the [full capture protocol](docs/capture_protocol.md) for the detailed folder layout and measurement log.
3. Run the matching workflow below: [photos](#current-photo-workflow), [video](#walkthrough-video-workflow), or [RGB-D/LiDAR](#rgb-d-capture-workflow). For reviewed room segments from one video, use the [multi-room video command](#supplied-dimensioned-apartment-plan).
4. After each run, follow the printed `Result:` path to `result.json`. Validate it with `python -m pipeline.validation "outputs\\<run>\\result.json"`.
5. For scored results, follow the [benchmark guide](benchmark/README.md) to fill the measurement manifest and run the evaluator. For automated visible-damage detections and preliminary quantities, use the [damage and takeoff workflow](#automated-damage-classification-and-scope-takeoff).
6. Check the [compliance matrix](docs/compliance_matrix.md) and [benchmark report](docs/benchmark_report.md) for the current implementation and evidence status.

## Current photo workflow

For one room, use a folder containing at least two overlapping JPEG, PNG, HEIC, or HEIF images directly inside it. For multiple rooms, use a collection root with one immediate subfolder per room, each containing 2–8 stills. The multi-room input reconstructs each room separately in one command; it does not yet produce the required stitched floor plan. Photos should overlap, be sharp, and show textured surfaces from different viewpoints. A single photo cannot recover 3D geometry. HEIC/HEIF photos are decoded and staged as JPEG for COLMAP; originals are preserved.

### Setup (Windows PowerShell)

Use 64-bit Python 3.12 (the latest replay was run on Python 3.12.14), then run these commands from the repository root:

```powershell
py -3.12 -m venv .venv
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

The root must contain at least two immediate room folders, for example `R01\`, `R02\`, and `C01\`; each must contain 2–8 JPEG, PNG, HEIC, or HEIF stills directly inside it. One result includes the independent reconstruction for each room and a joint COLMAP reconstruction attempt across all images, with room-folder membership reported for connected models. A weak per-room reconstruction is recorded as a room-level error rather than aborting the complete collection. The joint photo model uses a fixed seed and one CPU thread for repeatable membership; its settings and runtime are recorded separately in the result. The SVG pose review shows registered camera-center centroids and shared-model links in arbitrary SfM coordinates. It does not establish room boundaries, metric scale, gravity alignment, dimensions, adjacency, overlaps, or the homeowner-ready stitch. HEIC/HEIF staging applies EXIF orientation, preserves camera/focal metadata for COLMAP, and removes GPS from the staged JPEG. If EXIF contains camera make/model, the result records that automatically; add `--device "iPhone 16 Pro | iOS 19 | Camera"` to override it with the known hardware, OS, and capture app.

Per-room photo reconstruction limits COLMAP to four CPU threads. The cross-room exhaustive match/model stage uses one thread after the same image set produced 19–22 registered images across repeated multi-thread runs; two one-thread runs registered the exact same 20-image model. That joint stage is slower, so check the recorded run time against the 15-minute limit for larger collections. The settings are recorded under `reconstruction.summary.reconstruction_settings` and `joint_reconstruction_settings` in each result.

## Walkthrough video workflow

Pass a single video file directly, or a property folder containing one walkthrough video per room:

```powershell
python main.py "captures\walkthrough.mp4"
python main.py "captures\property_videos"
```

For an iPhone 15 or newer, set **Settings → Camera → Formats → Most Compatible** before recording and keep Apple ProRes off; Apple documents that new videos then use H.264, which reduces codec uncertainty on the Windows handoff. The pipeline accepts `.mov` and `.mp4`. See the [one-page capture protocol](docs/one_page_capture_protocol.md) for the exact walk and file layout.

For a multi-room folder, put one clip per room directly in the folder or one level down in folders named by room ID. The command returns one JSON result with separate sparse reconstructions for each clip; it does not align camera poses between clips or stitch a property plan. Each clip is sampled approximately four frames per second (up to 160 frames), saves selected frames and a contact sheet, then sends those frames through COLMAP sparse reconstruction with sequential matching. If the cap is reached, samples are spread across the complete clip and the result reports the effective rate and clip coverage. The result uses the shared JSON envelope with `capture.tier` set to `video`. This is sparse monocular reconstruction with arbitrary scale; it does not yet produce dimensioned rooms, classified openings, drift correction, or calibrated uncertainty.

Video results report `video_reconstruction_quality` in the result summary: sampled-frame count, model count, largest-model coverage, and per-model registration memberships. Multiple models trigger a limitation warning because the selected primary point cloud may cover only part of the walkthrough.

Each run creates a timestamped folder under `outputs` (or the selected output directory) containing:

- `result.json`: input file list, COLMAP summary, model counts, output paths, and scale limitations.
- `reconstruction\models\<id>\`: portable COLMAP text model (`cameras.txt`, `images.txt`, and `points3D.txt`).
- `reconstruction\models\<id>\points.ply`: sparse point cloud, viewable in CloudCompare, MeshLab, or another PLY viewer.
- `reconstruction\database.db`: COLMAP feature and match database used for the run.
- For video runs: sampled `video_frames\`, `video_sample_contact_sheet.png`, and `video_sampling.json`.

Photo and video models have arbitrary scale and do not place rooms into a measured property plan. RGB-D scan boundary polygons can now be stitched into an overlap-checked diagnostic candidate layout; accepted room dimensions and multi-room scan accuracy are still unverified. Damage detection is an optional hosted-image workflow described below. Standalone point-cloud ingestion is not implemented. Each capture run writes to a new folder, so previous results are retained.

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

An ARKitScenes raw scan folder is also accepted when it contains `lowres_wide/`, `lowres_depth/`, `confidence/`, `lowres_wide_intrinsics/`, and `lowres_wide.traj`:

```powershell
python main.py "D:\datasets\ARKitScenes\raw\Training\<video_id>"
```

This route matches each sparse trajectory pose to the nearest RGB, LiDAR depth, confidence, and intrinsics timestamps, rejecting matches more than 50 ms apart. Depth is interpreted as documented millimeters and Apple confidence value 0 is excluded. The camera-to-world trajectory and ARKit axis convention are assumptions pending comparison with a registered reference scan; output walls and room faces remain diagnostic only. Download only a suitable scan outside this repository, and confirm the dataset license permits your intended use. Capture and output folders are Git-ignored.

#### Reproduce the public LiDAR depth check

An optional downloader fetches ARKitScenes raw sample `42445884` (about 161 MB compressed), including low-resolution iPad Pro RGB-D and the dataset's FARO-projected high-resolution depth reference. This gives a real sensor-depth check without putting images or point clouds in Git:

```powershell
python -m pipeline.evaluation.download_arkitscenes_sample --output-dir "captures\_public_arkitscenes"
python main.py "captures\_public_arkitscenes\raw\Training\42445884" --output-dir "outputs\arkitscenes_public_sample"
python -m pipeline.evaluation.evaluate_arkitscenes_depth "captures\_public_arkitscenes\raw\Training\42445884" --output "outputs\arkitscenes_public_sample\arkitscenes_depth_evaluation.json"
python -m pipeline.validation "outputs\arkitscenes_public_sample"
```

The downloader records source URLs and SHA-256 hashes in the ignored capture folder. A fresh replay on the development workstation processed 78,343 points in 3.281 s; the separate depth evaluator matched 40 frame pairs and 350,043 valid pixels (2.18 cm MAE; 93.293% within 5 cm). This is iPad Pro sensor-depth evidence, not iPhone evidence or a room-dimension/whole-property-plan gate. Review the dataset terms before use; the media is not bundled or redistributed.

To create a drift-handling ablation from the same extracted capture, run it twice:

```powershell
python main.py "C:\captures\polycam-room" --pose-mode raw
python main.py "C:\captures\polycam-room" --pose-mode optimized
python pipeline\evaluation\drift_ablation.py --raw "outputs\<raw-run>\result.json" --optimized "outputs\<optimized-run>\result.json"
```

The evaluator requires results from the same capture path and reports diagnostic changes in observed floor coverage, pose translation spans, wall alignment, and geometry candidate counts. It does not establish accuracy or that optimized poses are better; that requires independent measured ground truth. The default report is written beside the optimized run as `drift_ablation.json`.

This creates a colored `rgbd_point_cloud.ply`, `floor_return_preview.png`, `wall_plane_candidates.png`, `wall_boundary_diagnostic.png`, and scan-derived stitched-plan review artifacts. The output records `reconstruction.summary.processing_runtime_seconds`, measured from capture type detection through reconstruction and artifact generation (excluding result JSON writing). The export samples every tenth pose/depth frame and every fourth pixel. The supplied bundle matches RGB presentation timestamps to depth odometry timestamps; Polycam joins exact shared keyframe IDs; ARKitScenes joins its sparse trajectory to the nearest RGB/depth/confidence/intrinsics frames and records offsets. The floor preview outlines the largest connected area of observed floor returns and records its polygon and observed-cell area. The wall pass reports projected planes, closed metric boundary candidates, provisional edge lengths, and nearby unclosed endpoint gaps. It checks candidate polygon overlap, excludes conflicts from the footprint sum, and reports shared-wall adjacency candidates. These are still diagnostics, not accepted room labels, identified doors/windows, or calibrated measurements: observed floor coverage is not the room footprint, an aligned candidate is not a verified wall, and a closed face is not proof of a room. Provisional edge lengths and areas have no calibrated confidence intervals. The pipeline treats depth values as millimeters, poses as camera-to-world transforms, and the least-varying camera-motion axis as vertical; validate these against capture documentation and ground truth. It does not create an accepted survey-grade floor plan.

Any line-intersection faces are copied to `property_plan.boundary_hypotheses`, `property_plan.room_candidates`, and `property_plan.stitched_plan.candidate_footprints` in `result.json`. `scan_stitched_plan.geojson` and `.svg` visualize the same-world-frame candidates, measured-looking area sum, overlaps excluded from the sum, and shared-edge adjacency candidates. `property_plan.rooms` remains empty until candidates are independently validated and accepted. The latest supplied RGB-D run produced one 3.304 m² four-sided candidate; this remains one review candidate, not a complete multi-room property plan.

Each RGB-D run also writes `geometry_review.geojson`, containing the observed floor-coverage outline, projected wall spans, candidate face polygons, and unclassified boundary-gap review targets, plus a vector `geometry_review.svg` sheet labeling the candidate area, side lengths, and open gaps. Gap features have a blank `review_label` field for manual annotation; they are not opening detections. These files use a capture-local coordinate frame with metres assumed and are intended for review, not as a survey-ready floor plan.

Photo, video, and RGB-D runs share the versioned output envelope defined in `schemas/property_capture_result.schema.json`. Every newly generated `result.json` is checked against that schema before it is written. Existing output folders can be checked in bulk:

```powershell
python -m pipeline.validation outputs
python -m pipeline.validation outputs\some_run\result.json
```

Until room extraction, metric calibration, and independent validation are implemented, unsupported plan and measurement fields are explicitly marked unavailable. Scan-derived candidate stitching is diagnostic only. The requirement-by-requirement status is tracked in `docs/compliance_matrix.md`.

The repeatable field procedure for matching room IDs across photo, video, LiDAR, staged-damage, and ground-truth captures is in [`docs/capture_protocol.md`](docs/capture_protocol.md). Extracted Polycam raw-data folders are supported; the ZIP itself must be extracted before running the pipeline. The printable one-page stock capture card is [`docs/one_page_capture_protocol.md`](docs/one_page_capture_protocol.md).

## Ground-truth benchmark scoring

### Supplied dimensioned apartment plan

When a builder supplies a floor-plan image with metric labels, keep it as a separate reference artifact. Create a reviewed annotation JSON containing image-coordinate room/connector outlines, transcribed dimensions, and adjacency; then render and check it with:

```powershell
python -m pipeline.geometry.render_reference_plan "captures\apartment_case_01\reference_plan.json" "outputs\apartment_case_01\stitched_plan"
```

The command writes an SVG overlay, PNG preview, GeoJSON, and a validation report. It rejects out-of-image or degenerate polygons and reports overlap intersections. Source-plan dimensions remain drawing references; image-pixel polygons are not converted to metres unless the drawing is independently calibrated. This is a human-reviewed floor-plan baseline, not a plan inferred from the photo/video reconstruction. Opening widths and missing measurement references stay unavailable.

For an edited single walkthrough, a reviewed `video_room_segments.json` can identify the time span for each room. The `--video-segments-json` option creates room-specific clips and processes them through the same multi-room video tier in one command:

```powershell
python main.py "captures\apartment_case_01\apartment_video.mp4" --video-segments-json "captures\apartment_case_01\video_room_segments.json"
```

The interval labels are human matches to supplied stills; the promotional video has edits and overlays. The multi-room video result records each clip interval and its reconstruction separately, and continues if an individual room fails. These per-room models remain arbitrary-scale and do not establish a stitched layout; use the separately rendered drawing as the current layout reference.

After photo and video runs, combine their recorded reconstruction coverage with the traced plan and explicit benchmark gaps using:

```powershell
python -m pipeline.evaluation.summarize_case_evidence "captures\apartment_case_01\reference_plan.json" "outputs\<photo-run>\result.json" "outputs\<video-run>\result.json" "outputs\apartment_case_01\evidence_report.json"
```

The currently available public/sample assets and their limits are listed in [`docs/public_dataset_inventory.md`](docs/public_dataset_inventory.md). The supplied RGB-D clip can generate same-scene photo input frames, but the tested sampled sets did not give COLMAP a valid initial image pair. The independent ISPRS still-photo sample does reconstruct as a single-room smoke test. Neither is independent iPhone multi-room benchmark evidence.

`pipeline/evaluation/benchmark.py` scores saved `result.json` files against a manually measured manifest. Follow [`benchmark/README.md`](benchmark/README.md), then copy `benchmark/ground_truth.template.json` to `benchmark/ground_truth.json`; the template has the required three-room-plus-connector structure but still needs measured values and capture runs. Record room areas, ceiling heights, wall lengths, opening widths, multi-room footprint/adjacency, and each run's result path. Add reviewed ID correspondences in each run's `wall_matches` and `opening_matches`. Record missed openings with a `null` prediction ID and every phantom opening in `phantom_opening_prediction_ids` so both count as detection errors. Reuse a `repeat_group` for captures of the same room and tier.

Run it with:

```powershell
python pipeline\evaluation\benchmark.py benchmark\ground_truth.json
```

The report scores opening width within 2 cm on at least 85% (including misses/phantoms), ceiling height within 1.5 cm, repeated ceiling spread within 1 cm, repeated wall spread within the larger of 1 cm or 0.5% of ground-truth length, photo/video wall lengths within 8%/3%, photo stitched footprint within 8% with ground truth inside its reported interval plus correct adjacency and no overlaps, and video whole-property footprint within 3%. When the manifest has same-room consumer-app measurements, it also reports LiDAR dimension-by-dimension absolute-error wins, ties, and losses, with the 70% win-or-tie gate. Saved processing times are compared with the 15-minute threshold, but must also be rerun on a clean machine. The report includes empirical interval coverage by tier and metric; drift ablation and benchmark-set composition require their own evidence.

For a scored before/after fix loop, use [`benchmark/fix_declaration.template.json`](benchmark/fix_declaration.template.json) after measured benchmark results identify a real failing gate, then run `python pipeline\evaluation\fix_loop.py benchmark\fix_declaration.json`. The report retains prediction error, gate movement, artifact hashes, and regeneration commands.

## Automated damage classification and scope takeoff

The optional detector uses Roboflow's public `wall-damage-detection/1` model for crack, flaking paint, missing material, and water damage. Its public model page reports 0.48 mAP@50, 0.644 precision, and 0.473 recall, so treat detections as review targets rather than inspection decisions. The hosted model and dataset page list a CC BY 4.0 license. Images are uploaded to Roboflow during inference; do not use this hosted route for images you are not allowed to share with that service. Capture images and generated outputs remain Git-ignored.

### Get an API key and run inference

1. Sign in to [Roboflow](https://app.roboflow.com/).
2. Open **Settings → API Keys** in the Roboflow workspace and copy the private API key. Keep it secret; do not paste it into source code, a JSON sidecar, or a Git-tracked file. Roboflow's hosted API uses the key for authentication; see its [hosted inference documentation](https://docs.roboflow.com/inference-classification/hosted-api).
3. From the Property Vision repository folder, set the key for this PowerShell window. `Read-Host` avoids putting the secret itself into the command history:

```powershell
$env:ROBOFLOW_API_KEY = Read-Host "Paste your Roboflow private API key"
python -m pipeline.damage_inference "captures\apartment_case_01\photo_tier" --output "outputs\damage_assessment.json"
```

Change the image-folder argument if your photos are stored elsewhere. The command searches that folder recursively, applies a default 0.25 confidence threshold, and writes `damage_assessment.json`. You can change the threshold with `--confidence 0.4`. Each detection becomes a schema-compatible image-space bounding polygon and preliminary scope line. Crack quantity is the bounding-box long axis; other quantities are bounding-box area. Units remain `px`/`px^2` unless a known scale for a nearly front-facing surface is supplied with `--scale-m-per-px 0.001`. Metric estimates remain partial because boxes are not pixel masks and perspective is not corrected. This does not estimate materials, labor, cost, or concealed damage. The sidecar records the model and that the images were uploaded to the provider.

### Apply detections to an existing run

List available results and choose the `result.json` produced for the same image capture:

```powershell
Get-ChildItem .\outputs -Recurse -Filter result.json | Select-Object -ExpandProperty FullName
$resultPath = (Read-Host "Paste the chosen result.json path, without surrounding quotes").Trim('"')
python -m pipeline.assessment "$resultPath" "outputs\damage_assessment.json"
python -m pipeline.validation "$resultPath"
```

The result path printed after application should end in `result.json`. The application step checks the sidecar shape and that every referenced evidence image still exists, then validates the updated result against the shared schema. Use `benchmark/assessment.template.json` instead when entering human-reviewed annotations. Automated predictions are marked as hosted-model output in the result limitations, not as human labels.

## Current limitations

- COLMAP's monocular reconstruction does not establish metric scale by itself.
- Sparse points and camera poses are not a floor plan. Multi-room photo/video inputs are accepted, but metric room placement and adjacency are unavailable from those tiers.
- RGB-D stitching and damage takeoff are diagnostic/proxy outputs; metric scale, completeness, detector quality on this property, and measured scope accuracy are not validated.
- The full case-study contract still needs three-tier capture evidence, a surveyed multi-room scan benchmark, a real-data-validated drift ablation, calibrated intervals, the incumbent comparison, and the fix loop.
