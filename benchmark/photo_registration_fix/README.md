# Photo joint-registration fix loop

This bundle compares two saved photo-tier runs on the same 23 staged apartment photos:

| Saved run | Photos in largest joint sparse model | Coverage |
| --- | ---: | ---: |
| Before configuration change | 8 / 23 | 34.783% |
| Fixed seed, one-thread joint mapper (`outputs/photo_final_verification/photo_tier_20261003T101629270757Z`) | 20 / 23 | 86.957% |

The after model includes images from all eight room folders. The full pipeline rerun completed in 92.984 seconds and passed the shared result validator; independent per-room models succeeded for the third bedroom and living/dining rooms only. This is a useful registration diagnostic, not a reconstructed apartment plan: the cloud is not metric-oriented or room-segmented, and the comparison does not establish room placement, adjacency, non-overlap, measured dimensions, or correct openings. Accordingly, the official `photo_whole_property_stitch` gate remains **NOT SCORED**. The 100% threshold in `fix_declaration.json` means “register every staged still in the largest model”; it is an operational diagnostic target, not an assessment acceptance threshold.

The small evidence JSON files retain the relevant saved-result fields, registered image basenames, room labels, and source `result.json` SHA-256. They exclude photos, point clouds, poses, and machine-specific paths. Rebuild those projections from the local `outputs/` results, then replay the benchmark and fix-loop reports with the commands in `fix_declaration.json`. Raw photos and generated 3D files remain outside this bundle.

The comparison is not a controlled ablation: fixed-seed and single-thread settings changed together, so their individual causal effect is unknown. The input is the arranged listing-photo collection, not an evaluator-captured iPhone run.
