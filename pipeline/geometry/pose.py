from dataclasses import dataclass

import numpy as np


@dataclass
class CameraPose:
    rotation: np.ndarray
    translation: np.ndarray