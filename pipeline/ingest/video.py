"""Video frame sampling for the walkthrough capture tier."""

import json
from pathlib import Path

import cv2
import numpy as np


def sample_walkthrough_video(
    video_path: Path,
    output_dir: Path,
    *,
    sample_fps: float = 4.0,
    max_frames: int = 160,
) -> dict:
    """Save a temporally sparse frame set for the existing SfM reconstructor."""
    video_path = Path(video_path).expanduser().resolve()
    output_dir = Path(output_dir).expanduser().resolve()
    if not video_path.is_file():
        raise FileNotFoundError(f"Walkthrough video does not exist: {video_path}")
    if sample_fps <= 0 or max_frames < 2:
        raise ValueError("Video sampling needs a positive sample rate and a frame cap of at least two.")

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise ValueError(f"OpenCV could not open walkthrough video: {video_path}")
    reported_fps = float(capture.get(cv2.CAP_PROP_FPS))
    reported_frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if not np.isfinite(reported_fps) or reported_fps <= 0:
        capture.release()
        raise ValueError("Video FPS metadata is missing or invalid; cannot sample deterministically.")

    frame_step = max(1, int(round(reported_fps / sample_fps)))
    nominal_sample_count = (reported_frame_count + frame_step - 1) // frame_step
    frame_cap_applied = nominal_sample_count > max_frames
    if frame_cap_applied:
        # Spread capped samples across the full capture instead of silently
        # stopping early and omitting the end of long walkthroughs.
        sample_indices = np.linspace(0, max(reported_frame_count - 1, 0), max_frames)
        sample_indices = np.unique(np.rint(sample_indices).astype(np.int64))
    else:
        sample_indices = np.arange(0, reported_frame_count, frame_step, dtype=np.int64)
    sample_index_set = set(int(index) for index in sample_indices)
    frame_dir = output_dir / "video_frames"
    frame_dir.mkdir(parents=True, exist_ok=False)
    sampled = []
    thumbnails = []
    frame_index = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if frame_index in sample_index_set:
                path = frame_dir / f"frame_{len(sampled) + 1:04d}.jpg"
                if not cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 95]):
                    raise IOError(f"Could not write sampled video frame: {path}")
                timestamp_s = frame_index / reported_fps
                sampled.append({
                    "sample_index": len(sampled),
                    "source_frame_index": frame_index,
                    "timestamp_s": round(timestamp_s, 3),
                    "file": path.name,
                })
                height, width = frame.shape[:2]
                thumb_width = 240
                thumb_height = max(1, int(round(height * thumb_width / width)))
                thumbnails.append(cv2.resize(frame, (thumb_width, thumb_height), interpolation=cv2.INTER_AREA))
            frame_index += 1
    finally:
        capture.release()

    if len(sampled) < 2:
        raise ValueError(
            f"Walkthrough video produced {len(sampled)} sampled frame(s); at least two are required."
        )

    columns = 4
    thumb_h, thumb_w = thumbnails[0].shape[:2]
    rows = int(np.ceil(len(thumbnails) / columns))
    sheet = np.zeros((rows * thumb_h, columns * thumb_w, 3), dtype=np.uint8)
    for index, thumbnail in enumerate(thumbnails):
        row, column = divmod(index, columns)
        y, x = row * thumb_h, column * thumb_w
        sheet[y:y + thumb_h, x:x + thumb_w] = thumbnail
        cv2.putText(sheet, f"{sampled[index]['timestamp_s']:.1f}s", (x + 6, y + 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (40, 240, 240), 1, cv2.LINE_AA)
    contact_sheet_path = output_dir / "video_sample_contact_sheet.png"
    if not cv2.imwrite(str(contact_sheet_path), sheet):
        raise IOError(f"Could not write video frame contact sheet: {contact_sheet_path}")

    duration_s = reported_frame_count / reported_fps if reported_frame_count else None
    covered_duration_s = sampled[-1]["timestamp_s"] - sampled[0]["timestamp_s"] if len(sampled) > 1 else 0.0
    summary = {
        "status": "sampled",
        "source_video": str(video_path),
        "reported_fps": round(reported_fps, 4),
        "reported_frame_count": reported_frame_count,
        "decoded_frame_count": frame_index,
        "duration_s_from_metadata": round(reported_frame_count / reported_fps, 3) if reported_frame_count else None,
        "target_sample_fps": sample_fps,
        "effective_sample_fps": round((len(sampled) - 1) / covered_duration_s, 4) if covered_duration_s else None,
        "frame_cap_applied": frame_cap_applied,
        "capture_coverage_percent": (
            round(min(100.0, sampled[-1]["timestamp_s"] / duration_s * 100), 2)
            if sampled and duration_s else None
        ),
        "frame_step": frame_step,
        "sampled_frame_count": len(sampled),
        "sampled_frames": sampled,
        "frame_directory": frame_dir.name,
        "contact_sheet": contact_sheet_path.name,
        "limitations": [
            "Frame sampling uses reported constant FPS and frame indices; variable-frame-rate timestamps are not read.",
            "Sampling can miss brief events and may omit viewpoints needed for a complete reconstruction even when samples span the full clip.",
            "The generated frame set is used for sparse SfM, not dense metric reconstruction.",
        ],
    }
    if frame_cap_applied:
        summary["limitations"].append(
            f"The {max_frames}-frame cap reduced the requested {sample_fps:g} fps rate to "
            f"{summary['effective_sample_fps']} fps while preserving {summary['capture_coverage_percent']}% clip coverage."
        )
    (output_dir / "video_sampling.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary
