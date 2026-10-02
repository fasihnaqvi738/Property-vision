# Device and tier accuracy matrix

Accuracy is **not established** for any tier. The runs below verify ingestion and runtime only; none is a laser/tape-ground-truthed case-study room. `unknown` means device identity was not recorded in the result.

| Tier | Input and device evidence | Pipeline evidence | Metric accuracy / expected error | Current support status |
|---|---|---|---|---|
| Photo | Five-image ISPRS indoor sample; device unknown; not an iPhone case-study capture. | 5/5 images registered; one sparse model; 2,437 points; 17.227 s with four COLMAP threads. | Scale is arbitrary. Room dimensions and error are not available. | JPEG/PNG photo folder ingestion demonstrated. Per-room plans and whole-property stitching are not demonstrated. |
| Video | 37.2-second RGB clip embedded in the supplied RGB-D bundle; device unknown; not an independent video-tier capture. | 143 frames sampled; six disconnected models; largest contains 25 frames (17.5%); 88.087 s. | Scale is arbitrary. Room dimensions and error are not available. | Video ingestion demonstrated. Continuous walkthrough reconstruction is not demonstrated. |
| LiDAR/RGB-D | Supplied `c00a170fe1` RGB-D bundle; device unknown. | 172 frames sampled; 528,384 points; 17.787 s; one four-sided 3.304 m² diagnostic boundary hypothesis; no opening candidates. | A diagnostic area hypothesis is present, but room accuracy and expected error are not established. | Supplied RGB-D processing demonstrated. Polycam raw adapter has not been run on a real Polycam export. |

## Minimum evidence to establish accuracy

Record the exact iPhone model, iOS version, capture app/version, and sensor availability for each run. Capture at least three rooms and a connector at all three tiers, repeat one room/tier, and record laser/tape wall lengths, ceiling heights, room areas, openings, and total footprint. Report signed errors, absolute errors, and sample counts by device and tier. Until those measurements exist, keep expected-error cells marked **not established**.
