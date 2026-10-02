import numpy as np


def compose_pose(
    rotation1,
    translation1,
    rotation2,
    translation2,
):
    rotation = rotation2 @ rotation1

    translation = (
        rotation2 @ translation1
        + translation2
    )

    return rotation, translation