import cv2
import numpy as np


def estimate_camera_pose(points1, points2, camera_matrix):
    essential_matrix, mask = cv2.findEssentialMat(
        points1,
        points2,
        camera_matrix,
        method=cv2.RANSAC,
        prob=0.999,
        threshold=1.0,
    )

    if essential_matrix is None:
        return None, None, None

    _, rotation, translation, pose_mask = cv2.recoverPose(
        essential_matrix,
        points1,
        points2,
        camera_matrix,
    )

    return rotation, translation, pose_mask