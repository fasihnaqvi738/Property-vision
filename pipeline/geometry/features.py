import cv2


def detect_features(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    sift = cv2.SIFT_create()
    keypoints, descriptors = sift.detectAndCompute(gray, None)

    return keypoints, descriptors


def match_features(descriptors1, descriptors2):
    matcher = cv2.BFMatcher()

    matches = matcher.knnMatch(
        descriptors1,
        descriptors2,
        k=2,
    )

    good_matches = []

    for match1, match2 in matches:
        if match1.distance < 0.75 * match2.distance:
            good_matches.append(match1)

    return good_matches