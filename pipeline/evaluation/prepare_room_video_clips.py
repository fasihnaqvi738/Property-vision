"""Extract reviewed room intervals from a property walkthrough for per-room SfM."""

import argparse
import json
from pathlib import Path

import cv2


def prepare_room_video_clips(
    video_path: Path,
    segment_manifest: Path,
    output_dir: Path,
    *,
    output_fps: float = 6.0,
    overwrite: bool = False,
) -> Path:
    video_path = video_path.expanduser().resolve()
    segment_manifest = segment_manifest.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if not video_path.is_file():
        raise FileNotFoundError(video_path)
    if not segment_manifest.is_file():
        raise FileNotFoundError(segment_manifest)
    if output_fps <= 0:
        raise ValueError("output_fps must be positive")

    source = cv2.VideoCapture(str(video_path))
    if not source.isOpened():
        raise ValueError(f"Could not open source walkthrough: {video_path}")
    source_fps = float(source.get(cv2.CAP_PROP_FPS))
    frame_count = int(source.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(source.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(source.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if source_fps <= 0 or frame_count <= 0 or width <= 0 or height <= 0:
        source.release()
        raise ValueError("Source video has invalid FPS, frame count, or frame dimensions")

    manifest = json.loads(segment_manifest.read_text(encoding="utf-8"))
    segments = manifest.get("segments", [])
    if not segments:
        source.release()
        raise ValueError("The segment manifest contains no segments")
    room_ids = [segment.get("room_id") for segment in segments]
    if any(not room_id or Path(room_id).name != room_id for room_id in room_ids):
        source.release()
        raise ValueError("Every room_id must be a simple folder name")
    if len(set(room_ids)) != len(room_ids):
        source.release()
        raise ValueError("Room IDs must be unique; combine separated intervals only after review")
    if output_dir.exists() and any(output_dir.iterdir()) and not overwrite:
        source.release()
        raise FileExistsError(f"Output is not empty (pass --overwrite to replace): {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    stride = max(1, int(round(source_fps / output_fps)))
    actual_fps = source_fps / stride
    outputs = []
    try:
        for segment in segments:
            start_s, end_s = float(segment["start_s"]), float(segment["end_s"])
            if start_s < 0 or end_s <= start_s or end_s * source_fps > frame_count:
                raise ValueError(f"Invalid interval for {segment['room_id']}: {start_s}–{end_s}s")
            room_id = segment["room_id"]
            room_dir = output_dir / room_id
            room_dir.mkdir(parents=True, exist_ok=True)
            clip_path = room_dir / f"{room_id}.mp4"
            if clip_path.exists() and not overwrite:
                raise FileExistsError(f"Refusing to overwrite existing clip: {clip_path}")
            writer = cv2.VideoWriter(
                str(clip_path), cv2.VideoWriter_fourcc(*"mp4v"), actual_fps, (width, height)
            )
            if not writer.isOpened():
                raise RuntimeError(f"Could not create MP4 segment: {clip_path}")

            start_frame = max(0, int(round(start_s * source_fps)))
            end_frame = min(frame_count, int(round(end_s * source_fps)))
            source.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
            frame_index = start_frame
            written = 0
            while frame_index < end_frame:
                ok, frame = source.read()
                if not ok:
                    break
                writer.write(frame)
                written += 1
                # Writer FPS is reduced by the same factor. Keep time spacing
                # consistent with the sampled frames without storing all source frames.
                frame_index += 1
                for _ in range(stride - 1):
                    if frame_index >= end_frame or not source.grab():
                        frame_index = end_frame
                        break
                    frame_index += 1
            writer.release()
            if written < 2:
                clip_path.unlink(missing_ok=True)
                raise ValueError(f"Interval for {room_id} yielded only {written} frame(s)")
            outputs.append({
                **segment,
                "clip": clip_path.relative_to(output_dir).as_posix(),
                "start_source_frame": start_frame,
                "end_source_frame_exclusive": end_frame,
                "source_fps": round(source_fps, 4),
                "clip_fps": round(actual_fps, 4),
                "frames_written": written,
            })
            (room_dir / "video_segment.json").write_text(
                json.dumps(outputs[-1], indent=2) + "\n", encoding="utf-8"
            )
    finally:
        source.release()

    result = {
        "source_video": str(video_path),
        "source_duration_s": round(frame_count / source_fps, 3),
        "segment_manifest": str(segment_manifest),
        "selection_method": manifest.get("selection_method"),
        "clips": outputs,
        "limitations": manifest.get("limitations", []),
    }
    manifest_path = output_dir / "room_video_clips_manifest.json"
    manifest_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("segments_json", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--output-fps", type=float, default=6.0)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    manifest = prepare_room_video_clips(
        args.video, args.segments_json, args.output,
        output_fps=args.output_fps, overwrite=args.overwrite,
    )
    print(f"Prepared room-specific video clips: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
