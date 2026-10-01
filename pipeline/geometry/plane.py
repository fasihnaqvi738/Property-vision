from dataclasses import dataclass


@dataclass
class Plane:
    normal: list[float]
    distance: float