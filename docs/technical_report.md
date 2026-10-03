# Property Vision technical report

**Engineering snapshot:** 2026-10-03  
**Status:** prototype report; not a passing accuracy submission.  
**Length:** intentionally kept within the six-page limit when rendered as a normal technical memo.

## 1. System and capture route

Property Vision accepts room-photo folders, video files or room-video collections, the supplied RGB-D bundle, and an extracted Polycam Raw Data folder. Photo/video features are reconstructed with CPU `pycolmap`/COLMAP; run-to-run reconstruction can vary even with identical inputs, so the saved model and registered-image counts must be treated as per-run diagnostics. Video is sampled with OpenCV before sparse reconstruction. RGB-D/LiDAR frames are back-projected using depth, intrinsics, and supplied poses; review-only floor and wall analyses produce point clouds and geometric hypotheses. Every new capture writes a timestamped result under `outputs/`, checks it against `schemas/property_capture_result.schema.json`, and preserves the source capture path.

The selected user route is the stock-capture protocol in `docs/capture_protocol.md`: iPhone Camera for photos and video, plus Polycam Space/LiDAR Raw Data on a Pro-class iPhone for depth. The protocol and one-command examples are in the repository. The project does not ship an iOS app. Device identity and iOS/app versions are unknown for the data presently tested. HEIC/HEIF stills are now decoded and converted to run-local JPEG staging files; original stills are left untouched. Install `requirements.txt` before the visit so the HEIF codec is present.

| Tier | Intended device/input | Current implementation | Verified status |
|---|---|---|---|
| Photo | iPhone 15+, 2–8 overlapping stills per room; JPEG/PNG/HEIC/HEIF | Independent room SfM and a joint feature-matching diagnostic | ISPRS single-room smoke run and supplied apartment stills; no accepted room plan or property stitch |
| Video | iPhone 15+, handheld `.mov`/`.mp4` room clips | Frame sampling and per-clip sparse SfM; reviewed time segments supported | Supplied edited listing video exercised; not a continuous iPhone walkthrough |
| LiDAR | Pro-class iPhone, extracted Polycam Raw Data; supplied RGB-D bundle also accepted | Depth back-projection, pose use, candidate floor/wall review, PLY and vector diagnostics | Supplied RGB-D sample exercised; no apartment LiDAR or actual Polycam export has been run |

## 2. Output and evidence

The shared JSON schema is enforced on serialization. It carries per-room geometry slots, stitched-plan slots, damage/scope sidecars, artifact paths, calibration status, drift status, and limitations. Unsupported measurements stay unavailable. A valid schema proves data shape, not geometric correctness or that a room has been reconstructed successfully. The rendered floor plan available today is a human-traced reference from the supplied plan image, not a plan inferred from the scans.

The strongest current RGB-D run, regenerated for this report from `captures/c00a170fe1`, sampled 172 of 1,715 frames and exported 528,384 colored points in 18.237 seconds. It generated a single four-sided 3.304 m² boundary candidate plus floor, wall, and geometry-review artifacts. Its dimensions have no independent measurement or calibrated interval; the candidate is not an accepted room. A fresh run's `result.json` passed the shared schema.

The latest default-code apartment photo run registered 5/23 stills in two of eight room groups independently; its joint COLMAP model registered 8/23 across six folder labels in 40.415 seconds. An earlier same-input default run registered 20/23 across all eight labels. This is a material run-to-run instability on the supplied images. Both results are shared SfM camera-pose diagnostics, not verified room placement: scale is arbitrary, and neither proves correct adjacency or a floor plan. A separate HEIC route run converted five generated HEIC derivatives of the ISPRS stills; all five registered and schema validation passed in 20.247 seconds. This confirms file-format handling, not native iPhone capture behavior. The edited 214-second promotional walkthrough was split into 11 human-reviewed intervals; 7/11 intervals made a sparse model and 4/11 had a model with at least three registered frames. Its run took 472.56 seconds. A fresh 37.2-second RGB-D sample video run sampled 143 frames and produced six disconnected models in 85.268 seconds (largest: 23 frames, 16.1%). These are sample/listing materials, not independent walk-in evidence. `docs/benchmark_report.md` records the gate-by-gate evidence and regeneration commands.

## 3. Layout, drift, and uncertainty

Room subfolder labels are carried through the photo result, but independent SfM coordinate frames do not place those rooms relative to one another. The joint photo model reports visual model connectivity only; it does not infer doors, adjacency, footprint, metric scale, or overlaps. The manual reference plan has 8 primary rooms/lobby, 5 ancillary spaces, 2 connectors, and 14 annotated adjacency records; these are traced in drawing pixels and are not scan predictions or an independently surveyed footprint.

The Polycam adapter can select raw or corrected camera poses and an evaluator can compare runs from the same export. No actual Polycam capture or ground-truthed raw/corrected ablation is available. The supplied RGB-D path uses its pose stream as provided. Consequently, this implementation does **not** demonstrate accumulated-drift correction on a multi-room capture.

There is no calibration dataset for any tier. Every predicted metric value lacks an empirically calibrated confidence interval, and the property-plan dimensions and openings remain unavailable. RGB-D candidate lengths/area are provisional geometry under unvalidated depth/pose/axis assumptions. Photo/video SfM has arbitrary scale. No measurement error, interval coverage, ceiling accuracy, opening accuracy, repeatability, or footprint accuracy can be claimed from these runs.

## 4. Gates and fix loop

No case-study accuracy gate is scored. The repository contains benchmark templates and an evaluator for openings, ceilings, repeated walls, footprints/adjacency, runtime, and a same-room incumbent comparison. The required measured manifest is not present. In particular, the current assets do not provide three rooms plus connector captured in all three tiers, staged damage in two classes, a same-tier repeat, laser/tape readings, or a Polycam/consumer-app comparison export.

A concrete input-path defect was found during the cold-run audit: HEIC was recognized by capture detection but excluded by photo enumeration, while capture loading eagerly decoded all full-resolution photos. The path now accepts HEIC/HEIF, validates/decode-stages images for COLMAP, and avoids retaining all 48 MP images at initial load. A generated HEIC smoke input decoded and staged successfully. This is an engineering reliability repair, **not** a fix-loop accuracy result: no measured failing accuracy gate or honest before/after metric exists yet. The declaration template must not be filled with a fabricated gate.

## 5. Walk-in risks and reproduction

The likely failure modes on a new property remain low texture, blur, motion, repeated patterns, poor doorway overlap, mirrors/glass, reflective or wet surfaces, low light, occlusion, and edited/variable-frame-rate video. Polycam export folder/version differences, iPhone codec differences, and corrected-pose conventions still require a real-device check. The stock route keeps the input offline after capture and the runtime has no service dependency, but the assessment's cold iPhone run cannot be certified without an actual iPhone 15+ capture and exported Pro LiDAR data.

From the repository root, install pinned dependencies, then run one of the README commands on the raw capture. Add `--device "model | OS version | app version"` to preserve the actual hardware/software identity. Validate a generated result with `python -m pipeline.validation outputs\\<run>\\result.json`. For the supplied RGB-D sample, the captured command was `python main.py captures\\c00a170fe1 --output-dir outputs`; the report and JSON result retain its runtime and artifact paths. Keep raw captures and generated visual files local/ignored; submit code, manifests, schemas, and report text without committing private or large capture imagery.

**Assessment:** reproducible prototype routes and output contract are in place; the central product claim (a metric, damage-aware, stitched plan from any of the three tiers) and the measured assessment gates remain unproven. The current repository should be described as a partial prototype, not a passing solution.
