# Property Vision: one-page capture card

Follow this card on the **same property** for whichever tier the assessment requests. Keep original files and use the same room IDs everywhere.

## Before the visit

- Install the repository's pinned Python dependencies once: `python -m pip install -r requirements.txt`.
- On the iPhone, set **Settings → Camera → Formats → Most Compatible** before collecting photos or video, and keep Apple ProRes off. New media is saved as JPEG/H.264 for broad handoff compatibility; see [Apple's format guide](https://support.apple.com/en-au/116944) and [ProRes settings](https://support.apple.com/en-au/109041).
- Label at least three rooms `R01`–`R03` and one connecting hall/landing `C01`.
- For the LiDAR tier, use a **Pro-class iPhone**, install Polycam, and [enable Developer Mode](https://learn.poly.cam/hc/en-us/articles/34295907278996-How-to-Access-Developer-Mode) **before capturing**. Export Raw Data on the same phone that made the capture; Developer Mode does not apply retroactively.
- Choose one furnished room for two staged damage examples from two classes. Keep the damage in place for every tier and photograph each example close-up and in room context.
- Measure every wall segment, floor area, ceiling height at two points, every door/window width, and the whole-property footprint with a laser or tape. Record units and endpoints. Capture one room twice in a fresh session at the same tier.

## Capture slowly

**Photos — stock iPhone Camera, iPhone 15 or newer:** Take **2–8 sharp photos per room**, walking the perimeter with about one-third overlap. Include corners and the doorway; photograph each connector from both ends. Avoid zoom, portrait mode, blur, fast movement, and blocked lenses. HEIC/HEIF is also accepted if you do not change the camera format.

**Video — stock iPhone Camera, iPhone 15 or newer:** With ProRes off, record **one 30–60 second landscape clip per room at 30 fps**. Most Compatible records H.264 video, which reduces codec uncertainty for the Windows pipeline. Start at the doorway, pause, walk slowly around the room with floor and walls visible, and finish facing the doorway. Record each connector separately. Do not edit, trim, or send through an app that recompresses the file.

**LiDAR — Polycam on a Pro-class iPhone:** Select Space/LiDAR capture and export **Raw Data**. Walk slowly around each room perimeter and through the doorway; scan the connector from both sides. Keep both the original export ZIP and the extracted folder.

## Hand off and run

Keep each modality in a separate collection root, with one room folder per ID. Copy originals directly from the phone without recompression. Save the iPhone model, iOS version, and app version; use that exact string in `--device` below.

```powershell
python main.py "captures\property_photos" --device "iPhone model | iOS version | Camera"
python main.py "captures\property_videos" --device "iPhone model | iOS version | Camera"
python main.py "captures\property_lidar\R01" --device "iPhone model | iOS version | Polycam version"
```

Run the LiDAR command once for each extracted room/connector export. Retain every `outputs\...\result.json`, the original sensor files, the completed capture log, raw measurement CSV, and damage labels. The current prototype writes schema-validated diagnostic results, but its scan-derived stitched plan and accuracy gates are not yet verified; do not substitute its output for the measured ground truth.
