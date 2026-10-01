import cv2
import numpy as np


def fit_plane(points):
    points = np.asarray(points)

    if len(points) < 3:
        return None

    centroid = points.mean(axis=0)
    centered = points - centroid

    _, _, vh = np.linalg.svd(centered)

    normal = vh[-1]
    normal = normal / np.linalg.norm(normal)

    distance = np.dot(normal, centroid)

    return normal, distance


def fit_plane_ransac(points, threshold=0.05):
    points = np.asarray(points, dtype=np.float32)

    if len(points) < 3:
        return None

    best_inliers = []

    iterations = 100

    for _ in range(iterations):
        sample = points[
            np.random.choice(len(points), 3, replace=False)
        ]

        p1, p2, p3 = sample

        normal = np.cross(p2 - p1, p3 - p1)

        norm = np.linalg.norm(normal)

        if norm == 0:
            continue

        normal = normal / norm

        distances = np.abs(
            np.dot(points - p1, normal)
        )

        inliers = np.where(distances < threshold)[0]

        if len(inliers) > len(best_inliers):
            best_inliers = inliers

    if len(best_inliers) < 3:
        return None

    plane = fit_plane(points[best_inliers])

    return plane, best_inliers