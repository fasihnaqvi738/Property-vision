# Property Vision capture protocol

**Capture route:** stock iPhone Camera for photo/video; Polycam Space (LiDAR) Raw Data on a Pro-class iPhone. Install Polycam from the App Store before the visit. Photo/video/RGB-D reconstruction runs locally. The optional Roboflow damage-classification workflow uploads the selected damage photos to its hosted service; see the [README API and privacy instructions](../README.md#automated-damage-classification-and-scope-takeoff) before using it.

## Prepare the property

Use the same furnished property in all tiers. Label at least three rooms `R01`–`R03` and one connector `C01`. Keep furniture and staged damage fixed. In one furnished room, stage two damage examples from two classes; label them and take close-ups plus a context photo.

Use a laser or tape to measure each wall segment, floor area, ceiling height at two points, each door/window width and sill height, and whole-property footprint. Sketch room connections. Preserve raw readings with units, endpoints, date, and measurer. Repeat one room in a fresh session at the same tier. Copy the two CSV templates in `benchmark/` and record device model, OS, app/version, date, tier, room, source file, and measurements.

## Capture

**Photos:** Before capture, set iPhone Settings → Camera → Formats → **Most Compatible** for JPEG/H.264 handoff ([Apple format guide](https://support.apple.com/en-au/116944)); keep Apple ProRes off for video ([Apple ProRes settings](https://support.apple.com/en-au/109041)). The pipeline also accepts HEIC/HEIF photos. Take **2–8 sharp overlapping photos per room** including corners and doorways. Walk slowly around the perimeter; keep the phone level and overlap neighboring views by about one third. Avoid zoom, portrait mode, blur, and blocked lenses. Photograph connectors from both ends. Save the original files directly in a folder named for each room; do not screenshot them or recompress them in a messaging app.

**Video:** With Most Compatible selected and ProRes off, record one **30–60 second landscape 30 fps clip per room**. This records H.264, reducing codec uncertainty for the Windows decoder. Start at the doorway, pause, slowly walk the perimeter with walls and floor visible, then finish facing the doorway. Record connectors separately. Avoid fast turns and blocked lenses. Save original clips in a room-named folder, or name them `R01.mov`, `R02.mov`, `C01.mov` in one folder (`.mov` and `.mp4` are accepted).

**LiDAR:** On a Pro iPhone, use Polycam Space/LiDAR mode. [Enable Developer Mode before capture](https://learn.poly.cam/hc/en-us/articles/34295907278996-How-to-Access-Developer-Mode); it does not apply retroactively. Slowly scan the perimeter and include the doorway; avoid fast turns and reflective surfaces where possible. Export **Raw Data** on the same device that made the capture. Keep the original ZIP and extracted folder; the latter must contain `keyframes/depth/`, RGB images, and camera JSON files. See Polycam's [Raw Data export instructions](https://learn.poly.cam/hc/en-us/articles/38276871185044-How-to-Extract-Raw-Data-and-What-Is-Included).

## Hand off and run

Keep originals unchanged. Package room folders, Polycam ZIP and extracted export, capture log, raw measurements, damage labels/photos, and connection sketch. Run once per tier collection:

```powershell
python main.py "captures\property_photos"  # one room folder per ID; 2–8 photos each
python main.py "captures\property_videos" # one clip per room
python main.py "captures\property_lidar\R01" # run once for each extracted room export
```

The photo pipeline records camera make/model from EXIF when available; it does not infer iOS or app versions. HEIC/HEIF staging applies EXIF orientation and retains camera/focal metadata for reconstruction while stripping GPS from the staged derivative; original files stay unchanged. Add `--device "iPhone 16 Pro | iOS 19 | Polycam 6"` (substitute the actual model and versions) to override that with the known hardware/software identity in each result JSON. The capture log template remains the source of full per-room and measurement metadata.

For optional automated visible-damage proposals and preliminary scope quantities, configure `ROBOFLOW_API_KEY` and follow the README's Roboflow workflow. Only photos explicitly submitted to that command are uploaded. Bounding-box quantities are review proxies, not measured repair scope; concealed-damage flags still require human evidence and rules.

Run the LiDAR command once per room/connector export. Keep every timestamped `outputs\...\result.json`. Add real measurements and result paths to `benchmark\ground_truth.json`, then run `python pipeline\evaluation\benchmark.py benchmark\ground_truth.json`.

**Known limitation:** photo/video multi-room inputs currently return per-room sparse reconstructions; no tier yet produces an accepted stitched dimensioned plan. Do not treat smoke runs or model geometry as measured benchmark truth.
