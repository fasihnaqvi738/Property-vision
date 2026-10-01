from dataclasses import dataclass
from pipeline.geometry.surface_types import SurfaceType
from pipeline.geometry.plane import Plane


@dataclass
class Surface:
    plane: Plane
    surface_type: SurfaceType