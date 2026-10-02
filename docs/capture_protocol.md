# Property Vision room capture protocol

Use this protocol for the same furnished property in all three tiers. Name each room `R01`, `R02`, and so on; name connecting halls `C01`. Do not move furniture or staged damage between tiers. Save original files unchanged and record device, app/version, date, room ID, and capture tier in a `capture_log.csv`.

## Before capture

Choose at least three rooms and one connecting hall. Include one furnished room with two staged, separately labeled damage examples. Mark the damage locations in a sketch and photograph them close-up. Measure an independent ground-truth set with a laser or tape: every wall segment, ceiling height at two points per room, each door/window width and sill height, and overall hall-to-room connections. Record units, endpoints, and who measured. Keep the raw readings; do not enter model predictions as ground truth.

## Photo tier — iPhone Camera

For every room, capture 4–8 still photos with the stock Camera app. Include all corners and doorways, overlap neighboring views by roughly one third, keep the phone level, and avoid digital zoom, portrait mode, and blurred shots. Capture the connector from each end. Save original-resolution JPEG/HEIC files in a separate folder per room; this prototype currently accepts JPEG/PNG, so convert HEIC copies to JPEG without deleting originals.

## Video tier — iPhone Camera

Record a separate 30–60 second landscape video per room at the phone’s standard 30 fps setting. Start at the doorway, pause briefly, walk slowly around the perimeter, keep walls and floor in view, and finish facing the doorway. Avoid fast turns and occluding the lens. Record connectors separately. Preserve original MP4/MOV files. The pipeline samples frames and produces sparse arbitrary-scale geometry; it does not yet produce validated dimensions.

## LiDAR tier — Polycam Space mode

On the LiDAR-equipped iPhone, enable [Polycam Developer Mode](https://learn.poly.cam/hc/en-us/articles/34295907278996-How-to-Access-Developer-Mode) **before** capturing. Capture each room in Space (LiDAR) mode with a slow perimeter sweep and the doorway visible. Export Raw Data on the same device that made the capture and retain the original ZIP plus extracted files. Polycam documents that raw export contains depth maps, camera parameters/poses, confidence images, and mesh information ([export guide](https://learn.poly.cam/hc/en-us/articles/38276871185044-How-to-Extract-Raw-Data-and-What-Is-Included)). This repository’s current LiDAR loader accepts the supplied RGB-D bundle layout, not Polycam’s raw ZIP directly; preserve these files for the planned adapter instead of converting them to a point cloud.

## Repeat and package

Repeat one room at the same tier from a fresh capture session, without consulting the first result. Keep the same room and measurement IDs across tiers. Package the capture log, original captures, ground-truth readings, damage labels, a room-connection sketch, and a note of any obstruction or missed surface. Do not claim accuracy from the prototype until its outputs have been scored against these readings.
