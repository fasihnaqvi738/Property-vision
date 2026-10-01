import numpy as np

from pipeline.ingest.capture import load_capture
from pipeline.geometry.features import detect_features, match_features
from pipeline.geometry.matching import (
    get_matched_points,
    estimate_homography,
)
from pipeline.geometry.pose_estimation import estimate_camera_pose
from pipeline.geometry.pose import CameraPose
from pipeline.geometry.triangulation import triangulate_points
from pipeline.geometry.planes import fit_plane_ransac


def run_pipeline(input_path: str):
    capture = load_capture(input_path)

    print("Capture ready")
    print("Path:", capture.path)
    print("Type:", capture.capture_type.value)
    print("Photos loaded:", len(capture.photos))
    print("Tier:", capture.metadata.tier)

    if len(capture.photos) < 2:
        return

    for i in range(len(capture.photos) - 1):
        image1 = capture.photos[i]
        image2 = capture.photos[i + 1]

        keypoints1, descriptors1 = detect_features(image1)
        keypoints2, descriptors2 = detect_features(image2)

        matches = match_features(
            descriptors1,
            descriptors2,
        )

        print(
            f"Pair {i + 1}-{i + 2}: "
            f"{len(matches)} matches"
        )

        if len(matches) < 4:
            continue

        points1, points2 = get_matched_points(
            keypoints1,
            keypoints2,
            matches,
        )

        matrix, mask = estimate_homography(
            points1,
            points2,
        )

        print(
            "Homography estimated:",
            matrix is not None,
        )

        if mask is not None:
            print("Inliers:", int(mask.sum()))

        height, width = image1.shape[:2]

        focal_length = width

        camera_matrix = np.array([
            [focal_length, 0, width / 2],
            [0, focal_length, height / 2],
            [0, 0, 1],
        ], dtype=np.float64)

        rotation, translation, pose_mask = estimate_camera_pose(
            points1,
            points2,
            camera_matrix,
        )

        print(
            "Rotation estimated:",
            rotation is not None,
        )

        print(
            "Translation estimated:",
            translation is not None,
        )

        if rotation is None or translation is None:
            continue

        pose = CameraPose(
            rotation=rotation,
            translation=translation,
        )

        print("Pose stored:", pose is not None)

        points_3d = triangulate_points(
            points1,
            points2,
            camera_matrix,
            rotation,
            translation,
        )

        print("3D points:", len(points_3d))

        plane_result = fit_plane_ransac(points_3d)

        if plane_result is not None:
            plane, inliers = plane_result

            print("Plane normal:", plane[0])
            print("Plane distance:", plane[1])
            print("Plane inliers:", len(inliers))