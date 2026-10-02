import argparse

from pipeline.pipeline import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a sparse reconstruction from room photos, walkthrough video, or an RGB-D capture."
    )
    parser.add_argument(
        "capture_folder",
        nargs="?",
        default="captures/photo_room",
        help="Photo folder, walkthrough video, supplied RGB-D bundle, or extracted Polycam raw LiDAR folder.",
    )
    parser.add_argument(
        "--output-dir",
        default="outputs",
        help="Parent folder for timestamped reconstruction results (default: outputs).",
    )
    args = parser.parse_args()

    result_path = run_pipeline(args.capture_folder, args.output_dir)
    print(f"Result: {result_path}")


if __name__ == "__main__":
    main()
