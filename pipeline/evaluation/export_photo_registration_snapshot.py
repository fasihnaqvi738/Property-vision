"""Export a path-free, media-free projection of a saved photo-tier result."""

import argparse
import hashlib
import json
from pathlib import Path


def export_snapshot(source_path: Path, output_path: Path) -> dict:
    source_path = source_path.resolve()
    output_path = output_path.resolve()
    result = json.loads(source_path.read_text(encoding="utf-8"))
    summary = result.get("reconstruction", {}).get("summary", {})
    joint = summary.get("joint_property_reconstruction") if isinstance(summary, dict) else None
    if not isinstance(joint, dict) or not joint:
        raise ValueError(f"No joint_property_reconstruction summary in {source_path}.")

    aggregate_keys = (
        "status", "method", "input_photo_count", "registered_image_count", "model_count",
        "largest_model_registered_photos", "largest_model_photo_coverage_percent",
        "largest_model_room_ids", "largest_model_room_count", "largest_model_spans_all_room_folders",
        "rooms_with_registered_images", "failure_reason", "point_clouds_are_metric_oriented_or_room_segmented",
    )
    model_keys = ("model_id", "registered_images", "registered_image_names", "sparse_points",
                  "registered_room_ids", "registered_room_count")
    models = joint.get("models", [])
    snapshot = {
        "evidence_kind": "photo_joint_registration_summary",
        "evidence_schema_version": 1,
        "source_artifact": {
            "basename": source_path.name,
            "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        },
        "capture": {"capture_id": result.get("capture", {}).get("capture_id")},
        "reconstruction": {
            "summary": {
                "joint_property_reconstruction": {
                    key: joint[key] for key in aggregate_keys if key in joint
                } | {
                    "models": [
                        {key: model[key] for key in model_keys if key in model}
                        for model in models if isinstance(model, dict)
                    ],
                }
            }
        },
        "projection_note": (
            "Generated from a saved result.json. Contains registration counts, room IDs, and image basenames only; "
            "excludes photographs, point clouds, camera poses, and machine-specific filesystem paths."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result_json", type=Path, help="Saved photo-tier result.json")
    parser.add_argument("output_json", type=Path, help="Path-free diagnostic snapshot JSON")
    args = parser.parse_args()
    snapshot = export_snapshot(args.result_json, args.output_json)
    joint = snapshot["reconstruction"]["summary"]["joint_property_reconstruction"]
    print(f"Photo registration snapshot: {args.output_json}")
    print(
        f"Largest-model coverage: {joint.get('largest_model_registered_photos')}/"
        f"{joint.get('input_photo_count')} photos; diagnostic only."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
