import cv2
import numpy as np


def get_matched_points(keypoints1, keypoints2, matches):
    points1 = np.float32(
        [keypoints1[m.queryIdx].pt for m in matches]
    )

    points2 = np.float32(
        [keypoints2[m.trainIdx].pt for m in matches]
    )

    return points1, points2



def estimate_homography(points1, points2):
    matrix, mask = cv2.findHomography(
        points1,
        points2,
        cv2.RANSAC,
        5.0,
    )

    return matrix, mask