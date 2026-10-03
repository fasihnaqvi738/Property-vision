# Case-study benchmark report

**Snapshot:** 2026-10-03. This report separates smoke-test measurements from the case-study gates. `NOT SCORED` means required same-property ground truth or capture evidence is absent; it must not be interpreted as a pass.

## Available runs

| Tier/source | Observed result | Runtime | What it verifies | What it does not verify |
|---|---|---:|---|---|
| Photo: five-image ISPRS indoor sample | JPEG: 5/5 registered, 2,437 points. HEIC smoke: five generated HEIC derivatives, 5/5 registered, 2,672 points | 17.227 s JPEG; 20.247 s HEIC | Single-room photo ingestion, HEIC decode/staging, and serialization | Native iPhone file/camera behavior, metric scale, dimensions, multi-room stitch, accuracy |
| Photo: supplied apartment stills (`outputs/photo_final_verification/photo_tier_20261003T101629270757Z`) | 23 stills in 8 labeled groups; 7/23 registered independently (3/3 third bedroom, 4/4 living/dining); 20/23 in the largest joint model across all 8 labels. Two joint-only repeat runs with fixed seed and one thread registered the same 20 images. | 92.984 s | Per-room folder handling, repeatable joint SfM on this input, and cross-folder pose connectivity | iPhone capture reliability, verified room placement, adjacency, metric geometry, or a passed photo benchmark |
| Video: supplied RGB-D sample clip | 143/143 selected frames sampled over 99.36%; six disconnected models; largest 23 frames (16.1%) | 85.268 s | `.mp4` video ingestion and sparse SfM | iPhone `.mov` codec behavior, unedited multi-room walk-in, cross-room placement, video footprint accuracy |
| Video: edited apartment listing | 11 reviewed intervals; 7/11 produced a model; 4/11 had at least 3 registered frames | 472.56 s | Video sampling and room-interval processing | Unedited handheld walk-in, cross-room placement, video footprint accuracy |
| LiDAR/RGB-D: supplied `c00a170fe1` bundle | 172/1,715 frames sampled; 528,384 colored points; one 3.304 m² diagnostic face candidate; schema valid | 18.237 s (fresh run) | RGB-D ingestion, artifact export, shared result schema | iPhone/Polycam data, accepted room boundary, surveyed metric accuracy |

The apartment reference drawing has a separate manual trace with 8 primary rooms/lobby, 5 ancillary spaces, 2 connectors, and 14 adjacency annotations. Per user instruction, its 11 complete printed room-dimension pairs and one partial pair are authoritative scoring targets for this apartment. There is no independent tape/laser cross-check; the pixel-coordinate trace remains separate from sensor predictions. These targets do not generalize to the unseen walk-in property.

The photo registration change has a replayable diagnostic bundle at `benchmark/photo_registration_fix/`: its largest sparse model increased from 8/23 to 20/23 photos on the saved listing-photo input. The bundle includes path-free result projections, SHA-256 provenance, before/after reports, and a fix-loop report. The diagnostic target moved in the desired direction, but its declared 100% operational target was not reached; more importantly, the official measured whole-property stitch gate remains **NOT SCORED** because sparse camera registration does not provide a floor plan or measured truth.

## Required gates

| Gate | Required evidence | Status |
|---|---|---|
| Opening widths within 2 cm on at least 85%, misses and phantoms counted | Labeled openings and independent widths | **NOT SCORED** |
| Ceiling height within 1.5 cm; same-room repeat spread within 1 cm | Repeated captures and laser/tape truth | **NOT SCORED** |
| Per-wall repeatability within 1 cm or 0.5% | Two same-tier captures and matched wall IDs | **NOT SCORED** |
| Photo footprint within ±8%, calibrated interval, correct adjacency, no overlaps | Same multi-room iPhone photo capture and measured footprint | **NOT SCORED** |
| Video footprint within ±3% | Same-property handheld iPhone walkthrough and measured footprint | **NOT SCORED** |
| Photo/video per-wall error within ±8%/±3% with tier calibration | Metric wall predictions and ground truth | **NOT SCORED** |
| LiDAR beats/ties consumer incumbent on ≥70% shared dimensions over 2 rooms | Same-room Polycam/consumer-app exports and truth | **NOT SCORED** |
| Drift on/off ablation | Same multi-room LiDAR capture with measured footprint | **NOT SCORED** |
| Two-class staged damage, concealed flags, and scope quantities | Labeled damage, surface truth, and rule evidence | **NOT SCORED** |
| Clean-machine capture command finishes within 15 minutes | Documented clean setup and actual assessment-device inputs | **PARTIAL** — existing smoke runs are under 15 minutes on this workstation; clean-machine and walk-in timing are unverified |

## Repeatability and incumbent comparison

No same-room repeated capture or consumer-app export is present. The repeatability and head-to-head tables therefore have zero comparable measured dimensions; no win/tie percentage can be reported. The `benchmark/ground_truth.template.json` and evaluator are ready for populated measurements, but the template is not data and has not been scored.

## Reproduction

Run `python main.py "captures\\c00a170fe1" --output-dir outputs` for the supplied RGB-D sample. Run `python main.py "captures\\apartment_case_01\\photo_tier" --output-dir outputs` for the apartment still collection and `python main.py "captures\\apartment_case_01\\apartment_video.mp4" --video-segments-json "captures\\apartment_case_01\\video_room_segments.json" --output-dir outputs` for the reviewed video intervals. Actual paths in the workspace may use a different video filename; use the path recorded in `captures/apartment_case_01/source_manifest.json`. Validate any fresh result using `python -m pipeline.validation outputs\\<run>\\result.json`.

All capture media and generated point clouds/previews remain local under ignored `captures/` and `outputs/`. Commit the small report/code/manifest artifacts only; do not force-add image or video files.
