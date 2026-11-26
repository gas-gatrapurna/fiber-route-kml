"""FTTx optical fiber route KML/KMZ generator and link budget calculator."""

from fiber_route_kml.cli import (
    calculate_optical_budget,
    compute_route_snap_to_road,
    decode_polyline,
    inject_route_to_kml,
    resolve_maps_url,
)

__all__ = [
    "calculate_optical_budget",
    "compute_route_snap_to_road",
    "decode_polyline",
    "inject_route_to_kml",
    "resolve_maps_url",
]
