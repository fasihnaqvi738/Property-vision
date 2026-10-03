# Public data strategy

The case brief says no captures are supplied, so this project uses public/sample data for development while keeping formal gates honest. A public dataset can test parts of the system; no current source supplies the required single property with all three capture tiers, staged damage, repeat capture, consumer-app exports, and independent laser/tape measurements.

## Data already in the workspace

| Source | Local path | Use | Limits / terms |
|---|---|---|---|
| ISPRS indoor sample | `captures/photo_room_isprs` | Five-image photo reconstruction smoke test. The source page identifies the camera and image dimensions. | One room/sample only; device is not the required iPhone. Its page does not state a redistribution license; retain the existing source note and do not redistribute the photos. |
| Supplied RGB-D sample | `captures/c00a170fe1` | RGB video, depth, confidence, camera matrix, odometry, and IMU exercise video and LiDAR/RGB-D ingestion. | Device and physical room coverage are unverified; it does not establish three rooms, staged damage, repeats, or tape/laser truth. |
| ARKitScenes raw video `42445884` (visit `422009`) | `captures/_public_arkitscenes/raw/Training/42445884` (downloaded locally; Git-ignored) | Actual Apple LiDAR RGB-D and sparse trajectory ingestion; low-resolution sensor depth compared with paired FARO-projected reference depth. The raw download manifest records asset URLs and SHA-256 hashes. | Captured on iPad Pro, not iPhone 15. One scan only; it does not test photo/video tiers, room dimensions, openings, a stitched plan, or the walk-in. The media is not redistributed; review the official terms linked below. |

To create same-scene photo input frames from the supplied RGB-D sample, the helper can sample 2–8 frames from a centered temporal window:

```powershell
python -m pipeline.evaluation.derive_photo_proxy "captures\c00a170fe1\rgb.mp4" "captures\public_proxy_photos_repro\R01" --count 5
```

The derived frames are not independent still-photo captures and do not pass the iPhone photo-tier benchmark gate. The script writes `R01_proxy_metadata.json` beside the room folder with selected source frame indices and the source-video SHA-256, keeping non-image files out of the photo folder. Actual COLMAP runs on five frames sampled across an 8-second window, five across a 2-second window, and eight across an 8-second window all failed to find a geometrically valid initial image pair. Treat this video’s frames as input-path exercise only, not a successful photo reconstruction.

## Public damage-development data

Roboflow Universe's [Defect Images – Property dataset](https://universe.roboflow.com/buildinghealth/defect-images-property-ssd5a) lists 376 object-detection images and eight classes including wall crack, mold, and water damage, with a CC BY 4.0 license on its project page. It is suitable for an offline damage-detection development baseline after downloading a version and preserving its labels and attribution. Bounding boxes alone do not supply pixel-accurate surface polygons, physical area, scale, or a concealed-damage rule, so those metrics remain unscored.

The Wikimedia Commons examples in `benchmark/damage/external_samples/README.md` are only two isolated illustration sources; they are not a property benchmark or damage model dataset.

## Sources considered but not selected

- [Zillow Indoor Dataset (ZInD)](https://github.com/zillow/zind) has multi-room panoramas, room-layout and opening annotations, camera poses, and floor plans, but its data terms are academic/non-commercial and downloading the full dataset requires account approval. This employment case study is not a suitable basis for assuming those terms allow product-development use.
- [Structured3D](https://github.com/bertjiazheng/Structured3D) includes multi-room synthetic houses, rendered images, depth, and 3D structure annotations. Its official project requires a signed data-use agreement before dataset download; the agreement-gated data is not available in this workspace, so it cannot currently supply a reproducible scored run.
- [ARKitScenes](https://github.com/apple/ARKitScenes) documents low-resolution RGB, Apple LiDAR depth/confidence, camera intrinsics and trajectory; some upsampling scans also include FARO-mesh depth projected into the wide-camera view. The new adapter and evaluator were exercised on raw sample `42445884`: 40 unique frame pairs, 350,043 valid pixels, 2.18 cm mean absolute depth error, and 93.293% within 5 cm. These are sensor-depth diagnostics, not the case-study room-plan gate; the device was iPad Pro. The [official data instructions](https://github.com/apple/ARKitScenes/blob/main/DATA.md), [raw format description](https://github.com/apple/ARKitScenes/blob/main/raw/README.md), [terms](https://github.com/apple/ARKitScenes/blob/main/LICENSE), and [paper](https://openreview.net/forum?id=tjZjv_qh_CE) are recorded in the download manifest. Media remains local and Git-ignored. One scan cannot supply the required same-property, all-tier, staged-damage benchmark.
- [ScanNet](https://www.scan-net.org/ScanNet/) has RGB-D video, camera poses, reconstructed surfaces, and semantic labels, but access requires agreeing to its terms and requesting data access.

## Reporting rule

Keep the device matrix and benchmark report split into `smoke/proxy evidence` and `case-study gate evidence`. Never transfer proxy metrics into the scored gates. Mark any gate without same-property ground truth as `NOT SCORED` or `UNVERIFIED`.
