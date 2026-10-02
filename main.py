import argparse
from datetime import datetime, timezone
from pathlib import Path

from pipeline.assessment import apply_assessment
from pipeline.pipeline import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a sparse reconstruction from room photos, walkthrough video, or an RGB-D capture."
    )
    parser.add_argument(
        "capture_folder",
        nargs="?",
        default="captures/photo_room",
        help="Photo folder/collection, walkthrough video/file collection, RGB-D bundle, or extracted Polycam Raw Data folder.",
    )
    parser.add_argument(
        "--output-dir",
        default="outputs",
        help="Parent folder for timestamped reconstruction results (default: outputs).",
    )
    parser.add_argument(
        "--pose-mode",
        choices=("auto", "raw", "optimized"),
        default="auto",
        help="Polycam LiDAR pose source; auto prefers corrected poses, or choose raw/optimized for comparison.",
    )
    parser.add_argument(
        "--assessment-json",
        type=Path,
        help="Optional human-reviewed damage/flag/scope sidecar JSON to apply after reconstruction.",
    )
    parser.add_argument(
        "--video-segments-json",
        type=Path,
        help="Optional reviewed timeline-to-room manifest; split one edited walkthrough before reconstructing per room.",
    )
    args = parser.parse_args()

    capture_input = args.capture_folder
    if args.video_segments_json:
        source_video = Path(args.capture_folder)
        if not source_video.is_file():
            parser.error("--video-segments-json requires capture_folder to name one video file.")
        from pipeline.evaluation.prepare_room_video_clips import prepare_room_video_clips

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        segmented_input = Path(args.output_dir) / f"{source_video.stem}_room_segments_input_{stamp}"
        manifest_path = prepare_room_video_clips(
            source_video, args.video_segments_json, segmented_input
        )
        print(f"Prepared room-specific video clips: {manifest_path}")
        capture_input = str(segmented_input)

    result_path = run_pipeline(capture_input, args.output_dir, pose_mode=args.pose_mode)
    if args.assessment_json:
        result_path = apply_assessment(result_path, args.assessment_json)
    print(f"Result: {result_path}")


if __name__ == "__main__":
    main()
