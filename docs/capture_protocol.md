# Property Vision capture protocol

**Capture route:** stock iPhone Camera for photo/video; Polycam Space (LiDAR) Raw Data on a Pro-class iPhone. Install Polycam from the App Store before the visit. The pipeline runs locally; it does not upload captures.

## Prepare the property

Use the same furnished property in all tiers. Label at least three rooms `R01`–`R03` and one connector `C01`. Keep furniture and staged damage fixed. In one furnished room, stage two damage examples from two classes; label them and take close-ups plus a context photo.

Use a laser or tape to measure each wall segment, floor area, ceiling height at two points, each door/window width and sill height, and whole-property footprint. Sketch room connections. Preserve raw readings with units, endpoints, date, and measurer. Repeat one room in a fresh session at the same tier. Copy the two CSV templates in `benchmark/` and record device model, OS, app/version, date, tier, room, source file, and measurements.

## Capture

**Photos:** On iPhone 15 or newer, set Camera → Formats → **Most Compatible**. Take **2–8 sharp overlapping photos per room** including corners and doorways. Walk slowly around the perimeter; keep the phone level and overlap neighboring views by about one third. Avoid zoom, portrait mode, blur, and blocked lenses. Photograph connectors from both ends. Save JPEGs directly in a folder named for each room.

**Video:** Record one **30–60 second landscape 30 fps clip per room**. Start at the doorway, pause, slowly walk the perimeter with walls and floor visible, then finish facing the doorway. Record connectors separately. Avoid fast turns and blocked lenses. Save original clips in a room-named folder, or name them `R01.mp4`, `R02.mp4`, `C01.mp4` in one folder.

**LiDAR:** On a Pro iPhone, use Polycam Space/LiDAR mode. Enable Developer Mode before capture. Slowly scan the perimeter and include the doorway; avoid fast turns and reflective surfaces where possible. Export **Raw Data** on the capture device. Keep the original ZIP and extracted folder; the latter must contain `keyframes/depth/`, RGB images, and camera JSON files.

## Hand off and run

Keep originals unchanged. Package room folders, Polycam ZIP and extracted export, capture log, raw measurements, damage labels/photos, and connection sketch. Run once per tier collection:

```powershell
python main.py "captures\property_photos"  # one room folder per ID; 2–8 photos each
python main.py "captures\property_videos" # one clip per room
python main.py "captures\property_lidar\R01" # run once for each extracted room export
```

Run the LiDAR command once per room/connector export. Keep every timestamped `outputs\...\result.json`. Add real measurements and result paths to `benchmark\ground_truth.json`, then run `python pipeline\evaluation\benchmark.py benchmark\ground_truth.json`.

**Known limitation:** photo/video multi-room inputs currently return per-room sparse reconstructions; no tier yet produces an accepted stitched dimensioned plan. Do not treat smoke runs or model geometry as measured benchmark truth.
