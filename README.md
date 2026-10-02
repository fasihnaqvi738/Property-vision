# Property Vision

An early computer-vision prototype for reconstructing a sparse 3D scene from one room's photos.

## Current photo workflow

Use a folder containing at least two overlapping JPEG or PNG images of the same room. Keep the images directly in that folder (not in subfolders). The photos should overlap, be sharp, and show textured surfaces from different viewpoints. A single photo cannot recover 3D geometry.

### Setup (Windows PowerShell)

Use 64-bit Python 3.13, then run these commands from the repository root:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Run one capture

```powershell
python main.py "captures\photo_room"
```

Pass any other room-photo folder as the first argument. To store results elsewhere, pass `--output-dir`:

```powershell
python main.py "C:\captures\living-room" --output-dir "C:\results"
```

Each run creates a timestamped folder under `outputs` (or the selected output directory) containing:

- `result.json`: input file list, COLMAP summary, model counts, output paths, and scale limitations.
- `reconstruction\models\<id>\`: portable COLMAP text model (`cameras.txt`, `images.txt`, and `points3D.txt`).
- `reconstruction\models\<id>\points.ply`: sparse point cloud, viewable in CloudCompare, MeshLab, or another PLY viewer.
- `reconstruction\database.db`: COLMAP feature and match database used for the run.

The model has arbitrary scale. It is not yet a dimensioned room plan and does not report walls, openings, room area, damage, or confidence intervals. Video, LiDAR, and HEIC ingestion are not implemented. Each run writes to a new folder, so previous results are retained.

## Current limitations

- COLMAP's monocular reconstruction does not establish metric scale by itself.
- Sparse points and camera poses are not a floor plan; there is no wall, opening, room-adjacency, or damage interpretation yet.
- The full case-study contract still needs three-tier capture, multi-room stitching, drift handling, ground-truthed benchmarks, calibrated intervals, the incumbent comparison, and the fix loop.
