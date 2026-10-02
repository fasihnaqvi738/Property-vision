# Case study compliance matrix

Status reflects the repository and artifacts available on 2026-10-02. “In progress” means a prototype exists but the stated gate is not demonstrated. A working colored point cloud is not counted as a room plan.

## Required deliverables

| Requirement | Evidence path or artifact | Status | Gap / next evidence |
|---|---|---|---|
| Compliance matrix | `docs/compliance_matrix.md` | In progress | Updated as gates are implemented and measured. |
| Capture route: installable iOS app or one-page stock protocol | None | Not started | Choose a capture app/tool, publish an unambiguous non-engineer protocol, and execute it. |
| Device and tier accuracy matrix | None | Not started | State supported iPhones and honest expected error by tier, backed by benchmark results. |
| Photo tier: 2–8 stills per room, per-room folders, stitched whole-property plan | `pipeline/reconstruction/colmap.py`, `pipeline/pipeline.py` | Prototype only | COLMAP produces sparse arbitrary-scale geometry; no room dimensions, multi-room stitching, or intervals. |
| Video tier: handheld walkthrough input | `pipeline/ingest/video.py`, `pipeline/pipeline.py`, `pipeline/reconstruction/colmap.py` | Prototype only | A single video file is sampled at about 4 fps (maximum 160 frames) and reconstructed as a sparse monocular image set using sequential matching and the shared JSON contract. Metric room plans, robust drift handling, and accuracy validation remain unavailable; the current RGB-D video is not an independent video-tier benchmark capture. |
| LiDAR tier: depth, poses, intrinsics | `pipeline/ingest/rgbd.py`, `pipeline/geometry/floor_returns.py`, `pipeline/geometry/wall_planes.py` | Prototype only | Supplied RGB-D bundle produces a colored point cloud, a polygon around the largest connected floor-return coverage component, deduplicated vertical-plane candidates, and snapped endpoint-cycle/open-gap evidence. Each candidate is compared with nearby outline support; line intersections produce bounded-face hypotheses for review. These remain observations, not an accepted room plan. Depth units, gravity axis, camera registration, and pose scale need ground-truth validation. |
| One command per capture on a clean machine in under 15 minutes | `main.py`, `README.md` | Partial | Photo, video, and supplied RGB-D commands exist; fresh-machine install and timing are unverified. |
| Shared JSON result contract across all tiers | `schemas/property_capture_result.schema.json`, `pipeline/results.py`, `pipeline/validation.py` | Implemented at serialization boundary | Photo, video, and RGB-D use the same result builder; each new result is schema-validated before writing, and existing files can be batch-checked with `python -m pipeline.validation outputs`. Initial scan: 18/20 outputs conform; the two failures are pre-contract RGB-D files without the shared envelope and should be regenerated if needed. This verifies shape and types, not measurement correctness. |
| Dimensioned per-room plan: walls, ceiling height, floor area, openings | `pipeline/geometry/wall_planes.py`, `pipeline/pipeline.py`, `schemas/property_capture_result.schema.json` | Prototype started | Suppresses overlapping near-coplanar detections, compares wall spans with observed floor coverage, and forms bounded-face hypotheses from line intersections. Diagnostic candidates are now surfaced in `property_plan.boundary_hypotheses` with vertices, provisional area/side lengths/angles, support IDs, and explicit uncalibrated uncertainty; they do not populate accepted `rooms`. The current capture yields one simple four-sided 3.304 m² candidate supported by four wall spans, while opening analysis yields no candidates and the two endpoint gaps fail shared-line checks. Robust room labeling, complete surfaces, calibrated uncertainty, and ground-truth validation remain. |
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

1. Regenerate or archive the two pre-contract RGB-D outputs if they are needed as deliverables; schema conformance does not validate geometric accuracy.
2. Validate and refine wall candidates against labeled geometry; turn supported boundary cycles into room segmentation, classified openings, dimensioned geometry, and a rendered plan; add drift correction and a measurable ablation.
3. Establish a named capture route and acquire the three-tier, multi-room benchmark with ground truth and repeats.
4. Improve fragmented video/photo whole-property reconstruction against the shared result contract.
5. Add damage/scope outputs, calibration, incumbent comparison, and the before/after fix-loop bundle.

The order can change when benchmark evidence identifies a more important failing gate; no accuracy claim should be made before that evidence exists.
