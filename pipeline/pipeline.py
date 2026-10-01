from pipeline.ingest.capture import load_capture
from pipeline.geometry.image import get_image_dimensions
from pipeline.geometry.features import detect_features
from pipeline.geometry.features import detect_features, match_features
from pipeline.geometry.matching import (
    get_matched_points,
    estimate_homography,
)
import numpy as np
from pipeline.geometry.pose_estimation import estimate_camera_pose
from pipeline.geometry.pose import CameraPose



def run_pipeline(input_path: str):
    capture = load_capture(input_path)

    print("Capture ready")
    print("Path:", capture.path)
    print("Type:", capture.capture_type.value)
    print("Photos loaded:", len(capture.photos))
    
    print("Tier:", capture.metadata.tier)   
    
    if len(capture.photos) >= 2:
        keypoints1, descriptors1 = detect_features(capture.photos[0])
        keypoints2, descriptors2 = detect_features(capture.photos[1])

        matches = match_features(descriptors1, descriptors2)

        if len(matches) >= 4:
            points1, points2 = get_matched_points(
                keypoints1,
                keypoints2,
                matches,
            )

            matrix, mask = estimate_homography(points1, points2)

            print("Matches:", len(matches))
            print("Homography estimated:", matrix is not None)

            if mask is not None:
                print("Inliers:", int(mask.sum()))
    
    
        height, width = capture.photos[0].shape[:2]

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

        print("Rotation estimated:", rotation is not None)
        print("Translation estimated:", translation is not None)

        if rotation is not None and translation is not None:
            pose = CameraPose(
                rotation=rotation,
                translation=translation,
            )

            print("Pose stored:", pose is not None)