"""Create a concise evidence audit for a reference plan plus photo/video runs."""

import argparse
import json
from pathlib import Path


def _read(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def summarize_case_evidence(reference_plan: Path, photo_result: Path, video_result: Path, output: Path) -> dict:
    reference_plan = Path(reference_plan).resolve()
    photo_result = Path(photo_result).resolve()
    video_result = Path(video_result).resolve()
    output = Path(output).resolve()
    plan = _read(reference_plan)
    photo = _read(photo_result)
    video = _read(video_result)
    photo_summary = photo["reconstruction"]["summary"]
    video_summary = video["reconstruction"]["summary"]
    joint = photo_summary.get("joint_property_reconstruction", {})
    video_quality = video_summary.get("video_reconstruction_quality", {})
    video_rooms = video_summary.get("rooms", [])
    video_room_evidence = []
    for room in video_rooms:
        models = room.get("models", [])
        sampling = room.get("sampling") or {}
        segment = room.get("source_segment") or {}
        registered_names = {
            name for model in models for name in model.get("registered_image_names", [])
        }
        largest_model_frames = max(
            (int(model.get("registered_images", 0)) for model in models), default=0
        )
        sampled_frames = int(sampling.get("sampled_frame_count", 0))
        video_room_evidence.append({
            "room_id": room.get("room_id"),
            "interval_s": [segment.get("start_s"), segment.get("end_s")],
            "match_confidence": segment.get("match_confidence"),
            "sampled_frames": sampled_frames,
            "unique_registered_frames": len(registered_names),
            "registered_frame_memberships": sum(
                int(model.get("registered_images", 0)) for model in models
            ),
            "largest_model_registered_frames": largest_model_frames,
            "largest_model_coverage_percent": (
                round(largest_model_frames / sampled_frames * 100, 1) if sampled_frames else None
            ),
            "model_count": len(models),
            "sparse_points": sum(int(model.get("sparse_points", 0)) for model in models),
            "has_sparse_model_with_3_or_more_frames": any(
                int(model.get("registered_images", 0)) >= 3 for model in models
            ),
            "failure_reason": room.get("failure_reason"),
        })
    rooms = []
    for room in photo_summary.get("rooms", []):
        rooms.append({
            "room_id": room.get("room_id"),
            "status": room.get("status"),
            "input_photos": room.get("input_photo_count"),
            "registered_photos": room.get("registered_photo_count"),
            "model_count": len(room.get("models", [])),
            "failure_reason": room.get("failure_reason"),
        })
    validation_path = output.parent / "stitched_plan" / "plan_validation.json"
    validation = _read(validation_path) if validation_path.is_file() else None
    report = {
        "case_id": plan["case_id"],
        "status": "partial_evidence_only",
        "reference_plan": {
            "source": str(reference_plan),
            "primary_rooms": sum(room.get("space_kind", "room") in {"room", "lobby"} for room in plan.get("rooms", [])),
            "ancillary_spaces": sum(room.get("space_kind") in {"bathroom", "walk_in_closet"} for room in plan.get("rooms", [])),
            "connectors": len(plan.get("connectors", [])),
            "adjacency_edges": len(plan.get("adjacency", [])),
            "plan_dimensions_transcribed": sum(bool(room.get("dimensions_m")) for room in plan.get("rooms", [])),
            "independent_metric_truth": False,
            "overlap_validation": validation.get("overlap_check") if validation else "not found",
            "opening_widths_available": sum(edge.get("opening_width_m") is not None for edge in plan.get("adjacency", [])),
        },
        "photo_run": {
            "result": str(photo_result),
            "total_room_groups": len(rooms),
            "groups_with_models": sum(room["status"] == "complete" for room in rooms),
            "registered_photo_total": photo_summary.get("total_registered_photos"),
            "room_results": rooms,
            "joint_reconstruction": {
                "status": joint.get("status"),
                "input_photo_count": joint.get("input_photo_count"),
                "registered_image_count": joint.get("registered_image_count"),
                "largest_model_photo_coverage_percent": joint.get("largest_model_photo_coverage_percent"),
                "largest_model_room_ids": joint.get("largest_model_room_ids", []),
                "is_metric_or_room_segmented": joint.get("point_clouds_are_metric_oriented_or_room_segmented"),
            },
            "runtime_seconds": photo_summary.get("processing_runtime_seconds"),
        },
        "video_run": {
            "result": str(video_result),
            "input_room_intervals": len(video_room_evidence),
            "intervals_with_models": sum(room["model_count"] > 0 for room in video_room_evidence),
            "intervals_with_at_least_3_registered_frames": sum(
                room["has_sparse_model_with_3_or_more_frames"] for room in video_room_evidence
            ),
            "room_results": video_room_evidence,
            "sampled_frames": video_quality.get(
                "sampled_frame_count",
                sum(room["sampled_frames"] for room in video_room_evidence),
            ),
            "capture_coverage_percent": video_quality.get("capture_coverage_percent"),
            "model_count": video_quality.get("model_count"),
            "largest_model_registered_frames": video_quality.get("largest_model_registered_frames"),
            "largest_model_coverage_percent": video_quality.get("largest_model_coverage_percent"),
            "sparse_points_across_models": video_quality.get("total_sparse_points_across_models"),
            "runtime_seconds": video_summary.get("processing_runtime_seconds"),
            "coordinate_scale": video_summary.get("scale"),
        },
        "benchmark_gates": {
            "status": "not_scored",
            "reason": "Photo/video runs do not provide metric room polygons, dimension intervals, or opening predictions; the plan labels are not independent measurement truth.",
            "missing_evidence": [
                "Apartment LiDAR/Polycam capture",
                "Independent tape/laser room, wall, ceiling, opening, and whole-property measurements",
                "Door/opening widths and verified opening correspondences",
                "Repeated same-room capture at each tier",
                "Independent incumbent/app measurements for LiDAR comparison",
                "Independent capture device/app/version metadata",
            ],
        },
        "interpretation": [
            "The rendered floor plan is a manually traced reference drawing, not inferred room geometry from the photos or video.",
            "The uploaded stills show promotional listing marks and overlap visually with the walkthrough; treat them as correlated evidence, not independent camera-tier captures.",
            "The segmented video clips were matched to plan room IDs by visual review. Their sparse models are arbitrary-scale and independent; their shared presence does not establish adjacency or a stitched 3D plan.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference_plan", type=Path)
    parser.add_argument("photo_result", type=Path)
    parser.add_argument("video_result", type=Path)
    parser.add_argument("output_json", type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize_case_evidence(args.reference_plan, args.photo_result, args.video_result, args.output_json), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
