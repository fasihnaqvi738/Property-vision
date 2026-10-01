import cv2
import numpy as np


def triangulate_points(
    points1,
    points2,
    camera_matrix,
    rotation,
    translation,
):
    projection1 = camera_matrix @ np.hstack(
        (np.eye(3), np.zeros((3, 1)))
    )

    projection2 = camera_matrix @ np.hstack(
        (rotation, translation)
    )

    points_4d = cv2.triangulatePoints(
        projection1,
        projection2,
        points1.T,
        points2.T,
    )

    points_3d = points_4d[:3] / points_4d[3]

    return points_3d.T