"""Derive photo-tier smoke-test frames from a supplied RGB-D sample video.

The output intentionally has no depth or poses. It is useful for exercising the
photo code path on the same visible scene as a video/RGB-D sample, but it is not
an independent iPhone photo capture or a benchmark replacement.
"""

import argparse
import hashlib
import json
from pathlib import Path

import cv2


def derive_photo_proxy(
    video_path: Path,
    output_room: Path,
    count: int = 5,
    span_seconds: float = 8.0,
) -> Path:
    video_path = Path(video_path).resolve()
    output_room = Path(output_room).resolve()
    if not video_path.is_file():
        raise FileNotFoundError(f"Input video was not found: {video_path}")
    if not 2 <= count <= 8:
        raise ValueError("count must be between 2 and 8 to match the photo-tier sample size.")
    if span_seconds <= 0:
        raise ValueError("span_seconds must be greater than zero.")
    if output_room.exists() and any(output_room.iterdir()):
        raise FileExistsError(f"Output room folder is not empty: {output_room}")

    counter = cv2.VideoCapture(str(video_path))
    if not counter.isOpened():
        raise ValueError(f"Could not open input video: {video_path}")
    try:
        reported_frames = int(counter.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = float(counter.get(cv2.CAP_PROP_FPS))
        if fps <= 0:
            raise ValueError(f"Video reports an invalid FPS value: {fps}.")

        # Container metadata can overstate the decodable frames, especially at EOF.
        # Count sequentially so the final target is always a frame the decoder read.
        decoded_frames = 0
        while True:
            ok, frame = counter.read()
            if not ok or frame is None:
                break
            decoded_frames += 1
        if decoded_frames < count:
            raise ValueError(
                f"Video has only {decoded_frames} decodable frames; at least {count} are required."
            )
        # The former full-clip spread could put images tens of seconds apart,
        # leaving no useful overlap for SfM. Use a short centered window so
        # this proxy can exercise photo matching on temporally adjacent views.
        frame_span = min(max(round(span_seconds * fps), count - 1), decoded_frames - 1)
        first_frame = round((decoded_frames - 1 - frame_span) / 2)
        frame_indices = [
            first_frame + round(i * frame_span / (count - 1))
            for i in range(count)
        ]
    finally:
        counter.release()

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise ValueError(f"Could not reopen input video for frame extraction: {video_path}")
    try:
        output_room.mkdir(parents=True, exist_ok=True)
        files = []
        current_frame = 0
        for sample_index, target_frame in enumerate(frame_indices, start=1):
            while current_frame <= target_frame:
                ok, frame = capture.read()
                if not ok or frame is None:
                    raise ValueError(
                        f"Decoder stopped at frame {current_frame} while extracting target frame {target_frame} from {video_path}."
                    )
                if current_frame == target_frame:
                    filename = f"proxy_{sample_index:02d}.jpg"
                    if not cv2.imwrite(str(output_room / filename), frame):
                        raise OSError(f"Could not write photo proxy image: {output_room / filename}")
                    files.append({
                        "file": filename,
                        "source_frame_index": target_frame,
                        "source_time_seconds": round(target_frame / fps, 3),
                    })
                current_frame += 1
    finally:
        capture.release()

    hasher = hashlib.sha256()
    with video_path.open("rb") as source_file:
        for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
            hasher.update(chunk)
    digest = hasher.hexdigest()
    metadata = {
        "proxy_type": "photo_tier_frames_derived_from_video",
        "source_video_name": video_path.name,
        "source_video_sha256": digest,
        "reported_frame_count": reported_frames,
        "decoded_frame_count": decoded_frames,
        "fps": fps,
        "selection": "uniform sampling in a centered temporal window for overlapping smoke-test views",
        "selection_span_seconds": round((frame_indices[-1] - frame_indices[0]) / fps, 3),
        "photos": files,
        "benchmark_eligible": False,
        "limitation": "These frames are derived from a video and are not independent iPhone still-photo captures, multi-room coverage, or ground-truthed measurements.",
    }
    metadata_path = output_room.parent / f"{output_room.name}_proxy_metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return output_room


def main() -> int:
    parser = argparse.ArgumentParser(description="Create 2–8 photo-tier smoke-test frames from a sample RGB-D video.")
    parser.add_argument("video", type=Path, help="Source RGB video, for example captures/c00a170fe1/rgb.mp4")
    parser.add_argument("output_room", type=Path, help="New or empty photo room folder for the extracted frames")
    parser.add_argument("--count", type=int, default=5, help="Number of frames to extract (2–8; default 5)")
    parser.add_argument("--span-seconds", type=float, default=8.0, help="Centered video window to sample (default: 8 seconds)")
    args = parser.parse_args()
    output = derive_photo_proxy(args.video, args.output_room, args.count, args.span_seconds)
    print(f"Derived {args.count} smoke-test photos: {output}")
    print("Not an independent photo capture or case-study benchmark evidence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
