# Case study compliance matrix

Status reflects the repository and artifacts available on 2026-10-02. “In progress” means a prototype exists but the stated gate is not demonstrated. A working colored point cloud is not counted as a room plan.

## Required deliverables

| Requirement | Evidence path or artifact | Status | Gap / next evidence |
|---|---|---|---|
| Compliance matrix | `docs/compliance_matrix.md` | In progress | Updated as gates are implemented and measured. |
| Capture route: installable iOS app or one-page stock protocol | None | Not started | Choose a capture app/tool, publish an unambiguous non-engineer protocol, and execute it. |
| Device and tier accuracy matrix | None | Not started | State supported iPhones and honest expected error by tier, backed by benchmark results. |
| Photo tier: 2–8 stills per room, per-room folders, stitched whole-property plan | `pipeline/reconstruction/colmap.py`, `pipeline/pipeline.py` | Prototype only | COLMAP produces sparse arbitrary-scale geometry; no room dimensions, multi-room stitching, or intervals. |
| Video tier: handheld walkthrough input | None; `CaptureType.VIDEO` is detected only | Not started | Implement video decoding, trajectory/depth or visual reconstruction, and the same plan output. |
| LiDAR tier: depth, poses, intrinsics | `pipeline/ingest/rgbd.py`, `pipeline/geometry/floor_returns.py`, `pipeline/geometry/wall_planes.py` | Prototype only | Supplied RGB-D bundle produces a colored point cloud, a polygon around the largest connected floor-return coverage component, deduplicated vertical-plane candidates, and snapped endpoint-cycle/open-gap evidence. Diagnostic previews show the coverage outline, candidate spans, and unresolved gaps; these remain observations, not an accepted room plan. Depth units, gravity axis, camera registration, and pose scale need ground-truth validation. |
| One command per capture on a clean machine in under 15 minutes | `main.py`, `README.md` | Partial | Photo and supplied RGB-D commands exist; fresh-machine install and timing are unverified; video is unsupported. |
| Shared JSON result contract across all tiers | `schemas/property_capture_result.schema.json`, `pipeline/results.py` | Partial | Photo and RGB-D emit the same envelope with unavailable outputs explicit; add video emitter and validate generated results against the schema. |
| Dimensioned per-room plan: walls, ceiling height, floor area, openings | `pipeline/geometry/wall_planes.py` | Prototype started | Suppresses overlapping near-coplanar planar detections and searches endpoint cycles and open gaps; no closed cycle or room is identified in the current capture. Still needs robust room segmentation, opening classification, measurements tied to complete surfaces, confidence intervals, and ground-truth validation. |
| Stitched whole-property plan and correct room adjacency | None | Not started | Place all rooms, detect connectors/adjacency, and prevent room overlaps. |
| Rendered plan | None | Not started | Produce a readable plan image/PDF from the same geometry as the JSON. |
| Per-surface damage regions, class, and metric extent | None | Not started | Build labeled staged-damage benchmark data and detect/measure regions. |
| Concealed-damage flags with fired rule | None | Not started | Define explainable rules and emit evidence for each flag. |
| Scope line items keyed to surfaces | None | Not started | Define item mapping and quantities from measured surfaces/damage. |
| Confidence interval on every measurement; calibration per tier | None | Not started | Collect ground truth, calibrate intervals independently by tier, and report coverage. |
| Benchmark: 3+ rooms plus connector | Supplied RGB-D capture `captures/c00a170fe1` | Unverified | Capture count/room topology has not been established; collect and label an explicit qualifying set. |
| Same multi-room set at photo, video, and LiDAR tiers | None | Not started | Acquire all three modalities for the same rooms. |
| Furnished room with staged damage in two classes | None | Not started | Capture, label, and measure the staged damage. |
| Repeat capture of at least one room at the same tier | None | Not started | Perform a second capture and compare outputs. |
| Laser/tape ground truth for all benchmark rooms | None | Not started | Submit raw readings and measurement protocol. |
| Accuracy gates: openings ≤2 cm on ≥85%; ceiling ≤1.5 cm, repeat ceiling spread ≤1 cm; repeat wall spread ≤1 cm or 0.5%; footprint ±8% photo; video ±3% | `pipeline/evaluation/benchmark.py`, `benchmark/ground_truth.template.json` | Evaluator ready; scores unavailable | Evaluates saved outputs against manually measured ground truth, counts missed/phantom openings, checks repeated runs and photo stitching, and reports interval coverage. No qualifying benchmark labels/results have been collected yet. |
| Drift handling and on/off ablation | `pipeline/ingest/rgbd.py` uses input poses as supplied | Fails stated gate | Add loop closure/pose-graph or plane-anchored correction and report footprint ablation. |
| Incumbent comparison on two rooms, beat/tie ≥70% shared dimensions | None | Not started | Select/name an app, save its exports, and report dimension-by-dimension errors. |
| Fix declaration and regenerable before/after | None | Not started | Name worst gate, root cause/evidence, predicted delta; ship fix and retain both runs. |
| Reproduction bundle and raw benchmark data | `captures/c00a170fe1` (local, ignored) | Partial | Add versioned acquisition instructions, ground truth, scripts, and data provenance; ensure no ignored local-only dependency. |
| Technical report ≤6 pages | None | Not started | Write after measurements and ablations exist. |
| Process evidence | Git history | In progress | Continue small, reviewable commits; ensure commits are pushed and reproducible. |

## Next engineering sequence

1. Validate photo and RGB-D results against the shared schema; add video output to the same contract.
2. Validate and refine wall candidates against labeled geometry; turn supported boundary cycles into room segmentation, classified openings, dimensioned geometry, and a rendered plan; add drift correction and a measurable ablation.
3. Establish a named capture route and acquire the three-tier, multi-room benchmark with ground truth and repeats.
4. Implement video and photo whole-property reconstruction against the same result contract.
5. Add damage/scope outputs, calibration, incumbent comparison, and the before/after fix-loop bundle.

The order can change when benchmark evidence identifies a more important failing gate; no accuracy claim should be made before that evidence exists.
