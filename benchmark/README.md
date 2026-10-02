# Build and score the case-study benchmark

The benchmark needs measured truth and saved pipeline outputs. Do not guess values or copy a model prediction into ground truth. The supplied `ground_truth.template.json` is a starter manifest, not data; duplicate it as `ground_truth.json` and fill it after collecting the evidence below. Use `capture_log.template.csv` to record each original sensor capture, and `raw_measurements.template.csv` to preserve tape/laser readings and room connections.

## Collect the required evidence

1. Capture at least three rooms and one connecting hall. Use the same room IDs for photo, video, and LiDAR captures. For the LiDAR tier, run `main.py` once per extracted Polycam room export. Repeat at least one room at the same tier in a fresh session.
2. Measure every room's floor area, ceiling height, each wall segment, each door/window width, and the whole property's footprint with a laser or tape. Record units, endpoints, room IDs, and the measurement source in the raw field notes. Record room adjacency from the connection sketch.
3. In one furnished room, stage and label two examples from two damage classes. Save the original images, measure each damaged area independently, and trace the visible region as pixel coordinates in its original image. Keep each label tied to a room and surface ID; do not estimate square metres from the image polygon without calibration.
4. Run `main.py` for each capture and preserve each run's `result.json`. A run record in the manifest points to one result and one ground-truth room. Repeats share the same `repeat_group` value.

For `raw_measurements.template.csv`, use `record_type` values `wall_length`, `floor_area`, `ceiling_height`, `opening_width`, `opening_sill_height`, `property_footprint`, or `adjacency`. Store lengths in metres and areas in square metres. Record each distinct wall/opening ID, both ceiling readings per room, and room-to-room edges. The JSON ground-truth manifest contains the benchmark summaries; keep the CSV as the raw measurement record.

## Fill the manifest

- `ground_truth_rooms`: one entry per measured room/hall. Use stable IDs such as `R01`, `R02`, `R03`, and `C01`.
- `walls`: one `{ "wall_id": "R01_W01", "length_m": 4.21 }` object per measured wall segment.
- `openings`: one `{ "opening_id": "R01_D01", "width_m": 0.91 }` object per measured door/window.
- `property.footprint_m2` and `property.adjacency`: measured whole-property area and edges such as `{ "room_a": "R01", "room_b": "C01" }`.
- `property.connector_room_ids`: IDs of halls/connectors, such as `["C01"]`; these are excluded from the three-room minimum.
- `staged_damage_examples`: at least two examples from distinct classes. Each needs a measured positive `extent_m2`, a `surface_id`, and one or more original-image regions, e.g. `{ "example_id": "D01", "room_id": "R01", "surface_id": "R01_W02", "damage_class": "<case-study class>", "extent_m2": 0.12, "regions": [{ "image_path": "damage/D01.jpg", "polygon_px": [[120, 55], [180, 65], [175, 100], [118, 92]] }] }`. Polygon points are `[x, y]` pixel coordinates in the named image; the measured metric extent is recorded separately.
- `runs`: add an entry per capture with `result_json`, `tier`, and `room_id`. Result paths may be relative to the manifest. Add `repeat_group` for repeat captures.
- `wall_matches`: map measured wall IDs to predicted `surface_id` values, for example `{ "ground_truth_wall_id": "R01_W01", "prediction_surface_id": "wall_1" }`.
- `boundary_hypothesis_matches`: optionally map a reviewed diagnostic face to a measured room, e.g. `{ "ground_truth_room_id": "R01", "prediction_candidate_id": "intersection_cycle_1" }`. The report shows area error in a separate diagnostics section; it never treats that face as an accepted room or applies an unverified pass threshold.
- `boundary_side_matches`: optionally map a diagnostic candidate side to a measured wall, e.g. `{ "ground_truth_room_id": "R01", "ground_truth_wall_id": "R01_W01", "prediction_candidate_id": "intersection_cycle_1", "candidate_side_index": 0 }`. Side indices follow `side_lengths_m` in the saved result; use the review drawing to confirm correspondence. The evaluator reports absolute and relative length error separately, without treating a candidate as an accepted wall.
- `opening_matches`: map measured opening IDs to predicted `opening_id` values. Use a null `prediction_opening_id` for a missed opening. List every extra predicted opening in `phantom_opening_prediction_ids`.
- For photo whole-property scoring, fill `room_matches` to map truth room IDs to predicted room IDs.

The current reconstruction does not emit accepted dimensioned rooms or classified openings, so many scores will be unavailable/fail until those capabilities exist. A mapped boundary hypothesis and its manually matched sides can still be compared with tape-measured room area and wall lengths as diagnostics. Those comparisons do not establish accepted rooms/walls or accuracy passes. Do not manually edit a result to make a gate pass. The evaluator scores dimensions and repeated-run consistency and checks staged-damage annotation readiness; automated damage detection and measurement are not implemented yet.

## Run scoring

From the repository root:

```powershell
python pipeline\evaluation\benchmark.py benchmark\ground_truth.json
```

The evaluator writes `benchmark_report.json` next to the manifest and prints each scored gate plus a separate evidence-readiness checklist for the three-room set, measured truth, all-tier coverage, repeat capture, and staged damage. `NOT SCORED` means there are no comparable measurements for that gate; it is distinct from a measured `FAIL`. Errors identify missing result files, invalid tiers, or unknown room IDs. A successful report is not itself a pass: inspect each readiness check, scored gate, metric row, missing prediction, and interval-coverage count.
