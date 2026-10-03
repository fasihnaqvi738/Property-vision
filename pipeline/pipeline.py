import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from pipeline.ingest.capture import load_capture
from pipeline.ingest.types import CaptureType
from pipeline.ingest.rgbd import reconstruct_rgbd
from pipeline.ingest.photo import (
    PHOTO_EXTENSIONS,
    discover_photos,
    infer_photo_device,
    stage_photo_images,
)
from pipeline.ingest.video import sample_walkthrough_video
from pipeline.results import build_result
from pipeline.validation import validate_result


def _write_result(result: dict, result_path: Path, started_at: float) -> Path:
    """Validate every tier's output before persisting the shared contract."""
    result["reconstruction"]["summary"]["processing_runtime_seconds"] = round(
        perf_counter() - started_at, 3
    )
    validate_result(result)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result_path


def _serialize_boundary_hypotheses(hypotheses: list[dict]) -> list[dict]:
    """Expose reviewable candidate geometry without asserting semantic rooms."""
    serialized = []
    for hypothesis in hypotheses:
        serialized.append({
            "candidate_id": hypothesis["hypothesis_id"],
            "status": "diagnostic_only",
            "vertices_xy_m": hypothesis["vertices_xy_m"],
            "area_m2": hypothesis["area_m2"],
            "side_lengths_m": [edge["length_m"] for edge in hypothesis.get("edges", [])],
            "side_supporting_wall_candidate_ids": [
                sorted({
                    str(support["candidate_id"])
                    for support in edge.get("supporting_wall_candidates", [])
                    if support.get("candidate_id")
                })
                for edge in hypothesis.get("edges", [])
            ],
            "interior_angles_degrees": hypothesis.get("interior_angles_degrees", []),
            "supporting_wall_candidate_ids": hypothesis.get("supporting_wall_candidate_ids", []),
            "measurement_uncertainty": {
                "status": "uncalibrated",
                "confidence_interval_m2": None,
                "reason": "No independent ground truth or calibrated error model is available.",
            },
        })
    return serialized


def _video_reconstruction_quality(sampling: dict, models: list[dict]) -> dict:
    """Summarize frame coverage and disconnected sparse models without claiming accuracy."""
    sampled = int(sampling.get("sampled_frame_count", 0))
    largest_model = max(models, key=lambda model: model.get("registered_images", 0), default=None)
    registered_memberships = sum(int(model.get("registered_images", 0)) for model in models)
    return {
        "status": "fragmented" if len(models) > 1 else "single_model" if models else "no_model",
        "sampled_frame_count": sampled,
        "target_sample_fps": sampling.get("target_sample_fps"),
        "effective_sample_fps": sampling.get("effective_sample_fps"),
        "frame_cap_applied": sampling.get("frame_cap_applied", False),
        "capture_coverage_percent": sampling.get("capture_coverage_percent"),
        "model_count": len(models),
        "largest_model_id": largest_model.get("model_id") if largest_model else None,
        "largest_model_registered_frames": int(largest_model.get("registered_images", 0)) if largest_model else 0,
        "largest_model_coverage_percent": (
            round(largest_model["registered_images"] / sampled * 100, 1)
            if largest_model and sampled else None
        ),
        "registered_frame_memberships_across_models": registered_memberships,
        "membership_count_may_include_the_same_frame_in_multiple_models": True,
        "total_sparse_points_across_models": sum(int(model.get("sparse_points", 0)) for model in models),
    }


def _unavailable_room_plan(room_id: str) -> dict:
    """Represent an input room without inventing dimensions or geometry."""
    def missing(unit: str, method: str) -> dict:
        return {"status": "unavailable", "value": None, "unit": unit,
                "interval": None, "method": method}

    return {
        "room_id": room_id,
        "status": "unavailable",
        "footprint": [],
        "walls": [],
        "ceiling_height": missing("m", "Photos have arbitrary scale; no calibrated room dimensions are available."),
        "floor_area": missing("m^2", "Photo reconstruction has no metric scale or validated floor segmentation."),
        "openings": [],
        "surfaces": [],
    }


def _video_collection_inputs(capture_root: Path, video_paths: list[Path]) -> list[tuple[str, Path]]:
    """Map one walkthrough clip per room from a shallow property folder."""
    mappings = []
    for video_path in video_paths:
        relative = video_path.relative_to(capture_root)
        if len(relative.parts) == 1:
            room_id = video_path.stem
        elif len(relative.parts) == 2:
            room_id = relative.parts[0]
        else:
            raise ValueError(
                f"Video {relative} is nested too deeply. Put clips directly in the property folder "
                "or one folder per room."
            )
        mappings.append((room_id, video_path))
    room_ids = [room_id for room_id, _ in mappings]
    if len(set(room_ids)) != len(room_ids):
        raise ValueError("Each video room must have exactly one clip and a unique room folder/name.")
    if not all(room_id.strip() for room_id in room_ids):
        raise ValueError("Video room IDs derived from folder or filename cannot be empty.")
    return sorted(mappings)


def run_pipeline(
    input_path: str,
    output_root: str = "outputs",
    *,
    pose_mode: str = "auto",
    device: str | None = None,
) -> Path:
    started_at = perf_counter()
    capture = load_capture(input_path)
    if device and device.strip():
        capture.metadata.device = device.strip()
    if capture.capture_type is CaptureType.RGBD:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        run_dir = Path(output_root) / f"{capture.path.name}_{timestamp}"
        summary = reconstruct_rgbd(capture.path, run_dir, pose_mode=pose_mode)
        if summary.get("capture_type") == "polycam_raw_lidar" and summary.get("pose_mode") == "optimized":
            drift_handling = {
                "status": "partial",
                "method": "Uses Polycam globally optimized camera poses; raw-pose comparison is available via the pose ablation evaluator.",
                "ablation_artifact": None,
            }
        else:
            drift_handling = None
        result = build_result(
            capture_id=capture.path.name,
            tier="lidar",
            source_format=summary.get("capture_type", "rgbd_bundle"),
            device=capture.metadata.device,
            input_files=(
                [
                    "keyframes/images/*",
                    "keyframes/corrected_images/*",
                    "keyframes/cameras/*.json",
                    "keyframes/corrected_cameras/*.json",
                    "keyframes/depth/*.png",
                    "keyframes/confidence/*.png",
                ]
                if summary.get("capture_type") == "polycam_raw_lidar"
                else [
                    "lowres_wide/*.png",
                    "lowres_depth/*.png",
                    "confidence/*.png",
                    "lowres_wide_intrinsics/*.pincam",
                    "lowres_wide.traj",
                ]
                if summary.get("capture_type") == "arkitscenes_raw_rgbd"
                else [
                    "rgb.mp4",
                    "camera_matrix.csv",
                    "odometry.csv",
                    "depth/*.png",
                    "confidence/*.png",
                ]
            ),
            reconstruction_method="RGB-D depth back-projection with supplied odometry poses",
            reconstruction_summary=summary,
            point_cloud=str(run_dir / "rgbd_point_cloud.ply"),
            limitations=summary["limitations"],
            drift_handling=drift_handling,
            raw_capture=[str(capture.path.resolve())],
            boundary_hypotheses=_serialize_boundary_hypotheses(
                summary.get("wall_plane_analysis", {})
                .get("room_boundary_hypotheses", {})
                .get("line_intersection_hypotheses", {})
                .get("hypotheses", [])
            ),
            debug_views=[
                str(run_dir / summary[key]["preview"])
                for key in ("floor_return_analysis", "wall_plane_analysis")
                if summary.get(key, {}).get("status") == "diagnostic_only"
            ] + (
                [str(run_dir / summary["wall_plane_analysis"]["boundary_preview"])]
                if summary.get("wall_plane_analysis", {}).get("boundary_preview")
                else []
            ) + (
                [str(run_dir / summary["geometry_review_geojson"])]
                if summary.get("geometry_review_geojson")
                else []
            ) + (
                [str(run_dir / summary["geometry_review_svg"])]
                if summary.get("geometry_review_svg")
                else []
            ),
        )
        return _write_result(result, run_dir / "result.json", started_at)

    if capture.capture_type is CaptureType.VIDEO:
        if pose_mode != "auto":
            raise ValueError("--pose-mode raw/optimized applies only to Polycam LiDAR exports.")
        video_extensions = {".mp4", ".mov", ".m4v", ".avi"}
        if capture.path.is_file():
            video_path = capture.path
        else:
            videos = sorted(
                path for path in capture.path.rglob("*")
                if path.is_file() and path.suffix.lower() in video_extensions
            )
            if len(videos) > 1:
                from pipeline.reconstruction.colmap import reconstruct_from_images

                room_inputs = _video_collection_inputs(capture.path, videos)
                timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                run_dir = Path(output_root) / f"{capture.path.name}_{timestamp}"
                reconstruction_settings = {
                    "max_image_size": 1280,
                    "num_threads": 4,
                    "max_num_features": 4096,
                    "matching_strategy": "sequential",
                    "sequential_overlap": 30,
                    "random_seed": 42,
                }
                room_summaries = []
                plan_rooms = []
                contact_sheets = []
                for room_id, room_video in room_inputs:
                    room_dir = run_dir / "room_videos" / room_id
                    segment_sidecar = room_video.parent / "video_segment.json"
                    source_segment = (
                        json.loads(segment_sidecar.read_text(encoding="utf-8"))
                        if segment_sidecar.is_file() else None
                    )
                    room_error = None
                    sampling = None
                    models = []
                    try:
                        sampling = sample_walkthrough_video(
                            room_video, room_dir, sample_fps=1.5, max_frames=60
                        )
                        models = reconstruct_from_images(
                            room_dir / sampling["frame_directory"],
                            run_dir / "reconstruction" / room_id,
                            **reconstruction_settings,
                        )
                    except (RuntimeError, ValueError, OSError) as error:
                        # Preserve other room runs when one short or edited interval
                        # cannot be decoded, sampled, or reconstructed.
                        room_error = str(error)
                    primary = max(
                        models,
                        key=lambda model: (model["registered_images"], model["sparse_points"]),
                        default=None,
                    )
                    room_summary = {
                        "room_id": room_id,
                        "source_video": room_video.relative_to(capture.path).as_posix(),
                        "sampling": sampling,
                        "models": models,
                        "primary_model_id": primary["model_id"] if primary else None,
                        "video_reconstruction_quality": (
                            _video_reconstruction_quality(sampling, models)
                            if sampling is not None else {
                                "status": "failed", "sampled_frame_count": 0,
                                "model_count": 0, "largest_model_registered_frames": 0,
                            }
                        ),
                        "failure_reason": room_error,
                    }
                    if source_segment is not None:
                        room_summary["source_segment"] = source_segment
                    room_summaries.append(room_summary)
                    plan_rooms.append(_unavailable_room_plan(room_id))
                    if sampling is not None:
                        contact_sheets.append(str(room_dir / sampling["contact_sheet"]))

                result = build_result(
                    capture_id=capture.path.name,
                    tier="video",
                    source_format="multi_room_walkthrough_videos",
                    device=capture.metadata.device,
                    input_files=[path.relative_to(capture.path).as_posix() for _, path in room_inputs],
                    reconstruction_method="Independent per-room frame sampling and COLMAP sequential mapping",
                    reconstruction_summary={
                        "capture_type": "multi_room_walkthrough_collection",
                        "rooms": room_summaries,
                        "room_count": len(room_summaries),
                        "scale": "arbitrary_per_room",
                        "reconstruction_settings": reconstruction_settings,
                    },
                    point_cloud=None,
                    limitations=[
                        "Each room video is sampled and reconstructed independently; camera poses are not aligned across clips.",
                        "The property result is not a stitched plan: room placement, adjacency, overlaps, and footprint are unavailable.",
                        "Monocular video has arbitrary scale and does not yield verified walls, ceiling heights, areas, or openings.",
                    ],
                    raw_capture=[str(capture.path.resolve())],
                    debug_views=contact_sheets,
                )
                result["property_plan"]["status"] = "partial"
                result["property_plan"]["rooms"] = plan_rooms
                return _write_result(result, run_dir / "result.json", started_at)
            if len(videos) != 1:
                raise ValueError(
                    f"Expected exactly one walkthrough video in {capture.path}; found {len(videos)}. "
                    "Pass the specific video file when a folder contains multiple videos."
                )
            video_path = videos[0]

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        run_dir = Path(output_root) / f"{capture.path.stem}_{timestamp}"
        run_dir.mkdir(parents=True, exist_ok=False)
        sampling = sample_walkthrough_video(video_path, run_dir)
        from pipeline.reconstruction.colmap import reconstruct_from_images

        reconstruction_settings = {
            "max_image_size": 1280,
            "num_threads": 4,
            "max_num_features": 4096,
            "matching_strategy": "sequential",
            "sequential_overlap": 30,
            "random_seed": 42,
        }
        models = reconstruct_from_images(
            run_dir / sampling["frame_directory"],
            run_dir / "reconstruction",
            **reconstruction_settings,
        )
        primary_model = max(
            models,
            key=lambda model: (model["registered_images"], model["sparse_points"]),
            default=None,
        )
        video_quality = _video_reconstruction_quality(sampling, models)
        limitations = [
            "Walkthrough frames are sampled from video and reconstructed as a sparse monocular image set.",
            "The reconstruction has arbitrary scale and does not yield verified room dimensions or openings.",
            "Video motion, rolling shutter, exposure changes, and repeated viewpoints can reduce image matching quality.",
            "Sampling and bundle adjustment do not implement a validated drift correction or loop-closure ablation.",
        ]
        if video_quality["status"] == "fragmented":
            limitations.append(
                f"COLMAP produced {video_quality['model_count']} disconnected models; the largest contains "
                f"{video_quality['largest_model_coverage_percent']}% of sampled frames, so the primary point cloud "
                "is not a continuous reconstruction of the full walkthrough."
            )
        result = build_result(
            capture_id=capture.path.stem,
            tier="video",
            source_format="walkthrough_video",
            device=capture.metadata.device,
            input_files=[str(video_path.name)],
            reconstruction_method="OpenCV video frame sampling followed by COLMAP incremental mapping",
            reconstruction_summary={
                "capture_type": "video",
                "sampling": sampling,
                "models": models,
                "primary_model_id": primary_model["model_id"] if primary_model else None,
                "scale": "arbitrary",
                "reconstruction_settings": reconstruction_settings,
                "video_reconstruction_quality": video_quality,
            },
            point_cloud=primary_model["point_cloud_ply"] if primary_model else None,
            limitations=limitations,
            raw_capture=[str(video_path.resolve())],
            debug_views=[str(run_dir / sampling["contact_sheet"])],
        )
        return _write_result(result, run_dir / "result.json", started_at)

    if capture.capture_type is not CaptureType.PHOTO:
        raise NotImplementedError(
            f"The photo reconstruction workflow does not support "
            f"{capture.capture_type.value} captures yet."
        )
    if pose_mode != "auto":
        raise ValueError("--pose-mode raw/optimized applies only to Polycam LiDAR exports.")

    from pipeline.reconstruction.colmap import reconstruct_from_images

    photo_files = discover_photos(capture.path)
    room_folders = sorted(
        folder for folder in capture.path.iterdir()
        if folder.is_dir() and any(
            file.is_file() and file.suffix.lower() in PHOTO_EXTENSIONS
            for file in folder.iterdir()
        )
    )
    if photo_files and room_folders:
        raise ValueError(
            "Photo input cannot mix images at the root with per-room photo folders. "
            "Put all photos directly in one folder or all room folders under a collection root."
        )
    if room_folders:
        if len(room_folders) < 2:
            raise ValueError("A multi-room photo collection needs at least two room subfolders.")
        room_inputs = []
        for folder in room_folders:
            images = sorted(
                file for file in folder.iterdir()
                if file.is_file() and file.suffix.lower() in PHOTO_EXTENSIONS
            )
            if not 2 <= len(images) <= 8:
                raise ValueError(
                    f"Room folder {folder.name!r} must contain 2 to 8 JPEG, PNG, or HEIC/HEIF stills; found {len(images)}."
                )
            room_inputs.append((folder.name, folder, images))

        if capture.metadata.device == "unknown":
            capture.metadata.device = infer_photo_device(
                [image for _, _, images in room_inputs for image in images]
            ) or "unknown"

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        run_dir = Path(output_root) / f"{capture.path.name}_{timestamp}"
        reconstruction_settings = {"num_threads": 4, "random_seed": 42}
        per_room = []
        plan_rooms = []
        all_input_files = []
        staged_room_inputs = []
        for room_id, folder, images in room_inputs:
            room_error = None
            try:
                staged_images = stage_photo_images(
                    images, run_dir / "photo_frames" / room_id
                )
                staged_room_inputs.append((room_id, staged_images))
                models = reconstruct_from_images(
                    staged_images[0].parent, run_dir / "reconstruction" / room_id,
                    **reconstruction_settings,
                )
            except (RuntimeError, ValueError, OSError) as error:
                # A weak room must not discard useful results from the other
                # rooms or prevent the cross-room matching diagnostic.
                models = []
                room_error = str(error)
            primary = max(
                models,
                key=lambda model: (model["registered_images"], model["sparse_points"]),
                default=None,
            )
            per_room.append({
                "room_id": room_id,
                "status": "complete" if models else "failed",
                "input_photo_count": len(images),
                "models": models,
                "primary_model_id": primary["model_id"] if primary else None,
                "registered_photo_count": len({
                    name for model in models for name in model.get("registered_image_names", [])
                }),
                "registered_image_memberships": sum(
                    model["registered_images"] for model in models
                ),
                "failure_reason": room_error,
            })
            all_input_files.extend(str(Path(room_id) / image.name) for image in images)
            plan_rooms.append(_unavailable_room_plan(room_id))

        # A joint SfM run can connect views through shared doorway/connector
        # imagery. It is a reconstruction diagnostic, not room placement or a
        # metrically scaled stitched floor plan.
        joint_image_dir = run_dir / "property_photo_frames"
        joint_image_dir.mkdir(parents=True, exist_ok=False)
        for room_id, images in staged_room_inputs:
            for image in images:
                shutil.copy2(image, joint_image_dir / f"{room_id}__{image.name}")
        joint_models = []
        joint_error = None
        joint_reconstruction_settings = {
            "num_threads": 1,
            "matching_strategy": "exhaustive",
            "random_seed": 42,
        }
        try:
            joint_models = reconstruct_from_images(
                joint_image_dir,
                run_dir / "property_reconstruction",
                **joint_reconstruction_settings,
            )
        except (RuntimeError, ValueError, OSError) as error:
            # Per-room results remain useful when views cannot form a joint
            # view graph; expose the failed stitch attempt in the result.
            joint_error = str(error)
        joint_model_summaries = []
        for model in joint_models:
            registered_names = model.get("registered_image_names", [])
            registered_rooms = sorted({
                room_id
                for room_id, _, _ in room_inputs
                if any(name.startswith(f"{room_id}__") for name in registered_names)
            })
            joint_model_summaries.append({
                **model,
                "registered_room_ids": registered_rooms,
                "registered_room_count": len(registered_rooms),
                "contains_multiple_rooms": len(registered_rooms) > 1,
            })
        largest_joint_model = max(
            joint_model_summaries,
            key=lambda model: model["registered_images"],
            default=None,
        )
        largest_joint_names = set(
            largest_joint_model.get("registered_image_names", [])
            if largest_joint_model else []
        )
        largest_joint_rooms = largest_joint_model["registered_room_ids"] if largest_joint_model else []

        # COLMAP text image records include camera poses in one shared but
        # arbitrary coordinate frame. Use their centers to report whether
        # folders are linked in the reconstruction; these are not room
        # boundaries, gravity-aligned plan coordinates, or metric dimensions.
        room_pose_points = {room_id: [] for room_id, _, _ in room_inputs}
        cross_room_links = set()
        for model in joint_model_summaries:
            model_rooms = model["registered_room_ids"]
            for index, room_a in enumerate(model_rooms):
                for room_b in model_rooms[index + 1:]:
                    cross_room_links.add((room_a, room_b))
            image_records = Path(model["model_text_dir"]) / "images.txt"
            if not image_records.is_file():
                continue
            for line in image_records.read_text(encoding="utf-8").splitlines():
                if not line.strip() or line.startswith("#"):
                    continue
                fields = line.split(maxsplit=9)
                if len(fields) != 10:
                    continue
                try:
                    qw, qx, qy, qz = map(float, fields[1:5])
                    tx, ty, tz = map(float, fields[5:8])
                except ValueError:
                    continue
                image_name = fields[9]
                room_id = next(
                    (candidate for candidate, _, _ in room_inputs
                     if image_name.startswith(f"{candidate}__")),
                    None,
                )
                if room_id is None:
                    continue
                # COLMAP stores world-to-camera quaternion/translation.
                rotation = [
                    [1 - 2 * (qy*qy + qz*qz), 2 * (qx*qy - qz*qw), 2 * (qx*qz + qy*qw)],
                    [2 * (qx*qy + qz*qw), 1 - 2 * (qx*qx + qz*qz), 2 * (qy*qz - qx*qw)],
                    [2 * (qx*qz - qy*qw), 2 * (qy*qz + qx*qw), 1 - 2 * (qx*qx + qy*qy)],
                ]
                translation = (tx, ty, tz)
                center = tuple(
                    -sum(rotation[row][axis] * translation[row] for row in range(3))
                    for axis in range(3)
                )
                room_pose_points[room_id].append(center)

        room_pose_summary = []
        for room_id, points in room_pose_points.items():
            if not points:
                room_pose_summary.append({"room_id": room_id, "registered_camera_count": 0,
                                          "centroid_sfm_xyz": None, "span_sfm_xyz": None})
                continue
            centroid = [sum(point[axis] for point in points) / len(points) for axis in range(3)]
            span = [max(point[axis] for point in points) - min(point[axis] for point in points)
                    for axis in range(3)]
            room_pose_summary.append({
                "room_id": room_id,
                "registered_camera_count": len(points),
                "centroid_sfm_xyz": [round(value, 6) for value in centroid],
                "span_sfm_xyz": [round(value, 6) for value in span],
            })
        photo_pose_diagnostic = {
            "status": "diagnostic_only" if cross_room_links else "unavailable",
            "coordinate_frame": "arbitrary COLMAP SfM coordinates; not gravity aligned or metric",
            "rooms": room_pose_summary,
            "shared_model_room_pairs": [
                {"room_a": room_a, "room_b": room_b, "status": "visual_model_connectivity_only"}
                for room_a, room_b in sorted(cross_room_links)
            ],
            "adjacency": "unavailable; shared SfM model membership does not prove a doorway or room adjacency",
            "footprint": "unavailable; camera centers do not define room boundaries",
        }
        from pipeline.geometry.render_photo_poses import render_photo_pose_diagnostic
        photo_pose_review = render_photo_pose_diagnostic(
            photo_pose_diagnostic, run_dir / "photo_pose_review.svg"
        )
        photo_pose_diagnostic["review_svg"] = str(photo_pose_review)

        limitations = [
            "Each photo subfolder is reconstructed independently; camera poses do not place rooms in a shared property frame.",
            "The multi-room result is not a stitched floor plan: room adjacency, overlaps, and whole-property footprint are unavailable.",
            "Monocular photo reconstructions have arbitrary scale; walls, ceiling heights, floor areas, and openings are unavailable.",
            "Use the same stable room-folder names across tiers; independent captures do not themselves establish matching room identities.",
        ]
        result = build_result(
            capture_id=capture.path.name,
            tier="photo",
            source_format="multi_room_photo_folders",
            device=capture.metadata.device,
            input_files=all_input_files,
            reconstruction_method="Independent per-room COLMAP incremental mapping",
            reconstruction_summary={
                "capture_type": "multi_room_photo_collection",
                "rooms": per_room,
                "room_count": len(per_room),
                "total_registered_photos": sum(item["registered_photo_count"] for item in per_room),
                "scale": "arbitrary_per_room",
                "reconstruction_settings": reconstruction_settings,
                "joint_reconstruction_settings": joint_reconstruction_settings,
                "joint_property_reconstruction": {
                    "status": "diagnostic_only" if joint_models else "failed",
                    "method": "COLMAP exhaustive matching over all room-folder photos",
                    "input_photo_count": len(all_input_files),
                    "models": joint_model_summaries,
                    "registered_image_count": len({
                        name for model in joint_models
                        for name in model.get("registered_image_names", [])
                    }),
                    "registered_image_memberships": sum(
                        model["registered_images"] for model in joint_models
                    ),
                    "model_count": len(joint_model_summaries),
                    "largest_model_registered_photos": len(largest_joint_names),
                    "largest_model_photo_coverage_percent": (
                        round(len(largest_joint_names) / len(all_input_files) * 100, 1)
                        if all_input_files else None
                    ),
                    "largest_model_room_ids": largest_joint_rooms,
                    "largest_model_room_count": len(largest_joint_rooms),
                    "largest_model_spans_all_room_folders": (
                        set(largest_joint_rooms) == {room_id for room_id, _, _ in room_inputs}
                    ),
                    "rooms_with_registered_images": sorted({
                        room_id for model in joint_model_summaries
                        for room_id in model["registered_room_ids"]
                    }),
                    "failure_reason": joint_error,
                    "point_clouds_are_metric_oriented_or_room_segmented": False,
                },
                "cross_room_pose_diagnostic": photo_pose_diagnostic,
            },
            point_cloud=None,
            limitations=limitations,
            raw_capture=[str(capture.path.resolve())],
        )
        result["property_plan"]["status"] = "partial"
        result["property_plan"]["rooms"] = plan_rooms
        result["property_plan"]["stitched_plan"]["status"] = "unavailable"
        result["artifacts"]["debug_views"] = [str(photo_pose_review)]
        return _write_result(result, run_dir / "result.json", started_at)

    if not photo_files:
        raise ValueError(
            f"No JPEG, PNG, HEIC, or HEIF photos found directly in {capture.path} or in its immediate room subfolders."
        )

    if capture.metadata.device == "unknown":
        capture.metadata.device = infer_photo_device(photo_files) or "unknown"

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = Path(output_root) / f"{capture.path.name}_{timestamp}"
    reconstruction_settings = {"num_threads": 4, "random_seed": 42}
    staged_images = stage_photo_images(photo_files, run_dir / "photo_frames")
    models = reconstruct_from_images(
        staged_images[0].parent, run_dir / "reconstruction", **reconstruction_settings
    )
    primary_model = max(
        models,
        key=lambda model: (model["registered_images"], model["sparse_points"]),
        default=None,
    )

    limitations = [
        "Monocular photo reconstruction has no metric scale without a known dimension or depth sensor.",
        "This output is a sparse 3D reconstruction, not a measured floor plan.",
    ]
    result = build_result(
        capture_id=capture.path.name,
        tier="photo",
        source_format="room_photo_folder",
        device=capture.metadata.device,
        input_files=[path.name for path in photo_files],
        reconstruction_method="COLMAP incremental mapping",
        reconstruction_summary={
            "models": models,
            "scale": "arbitrary",
            "reconstruction_settings": reconstruction_settings,
        },
        point_cloud=primary_model["point_cloud_ply"] if primary_model else None,
        limitations=limitations,
        raw_capture=[str(capture.path.resolve())],
    )
    return _write_result(result, run_dir / "result.json", started_at)
