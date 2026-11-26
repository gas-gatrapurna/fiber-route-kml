#!/usr/bin/env python3
"""FTTx optical fiber route KML/KMZ generator and optical link budget CLI."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

ROUTES_API_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"


def resolve_maps_url(url: str) -> list[dict]:
    """Resolve a Google Maps directions URL (including shortlinks) into waypoints."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; fiber-route-kml/0.1)"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        final_url = resp.geturl()

    waypoints: list[dict] = []
    matches = re.findall(r"!1d([-\d.]+)!2d([-\d.]+)", final_url)
    if matches:
        for idx, (lng_str, lat_str) in enumerate(matches):
            waypoints.append(
                {
                    "lat": float(lat_str),
                    "lng": float(lng_str),
                    "name": f"Waypoint {idx + 1}",
                }
            )
    else:
        coords = re.findall(r"(-?\d+\.\d+),\s*([-\d.]+)", urllib.parse.unquote(final_url))
        for idx, (lat_str, lng_str) in enumerate(coords):
            waypoints.append(
                {
                    "lat": float(lat_str),
                    "lng": float(lng_str),
                    "name": f"Point {idx + 1}",
                }
            )

    return waypoints


def decode_polyline(polyline_str: str) -> list[tuple[float, float]]:
    """Decode an encoded Google Maps polyline string into (lat, lng) tuples."""
    index, lat, lng = 0, 0, 0
    coordinates: list[tuple[float, float]] = []
    length = len(polyline_str)

    while index < length:
        shift, result = 0, 0
        while True:
            byte = ord(polyline_str[index]) - 63
            index += 1
            result |= (byte & 0x1F) << shift
            shift += 5
            if byte < 0x20:
                break
        dlat = ~(result >> 1) if (result & 1) else (result >> 1)
        lat += dlat

        shift, result = 0, 0
        while True:
            byte = ord(polyline_str[index]) - 63
            index += 1
            result |= (byte & 0x1F) << shift
            shift += 5
            if byte < 0x20:
                break
        dlng = ~(result >> 1) if (result & 1) else (result >> 1)
        lng += dlng

        coordinates.append((lat / 100000.0, lng / 100000.0))

    return coordinates


def compute_route_snap_to_road(
    waypoints: list[dict],
    sa_key_path: str | None = None,
    solution_id: str | None = None,
) -> dict:
    """Call Google Maps Routes API (computeRoutes) with snap-to-road waypoints."""
    if len(waypoints) < 2:
        raise ValueError("At least 2 waypoints (origin and destination) are required.")

    key_path = sa_key_path or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    if not key_path:
        raise ValueError(
            "Service Account key path is required via --key or GOOGLE_APPLICATION_CREDENTIALS."
        )

    key_file = Path(key_path)
    if not key_file.exists():
        raise FileNotFoundError(f"Service Account key not found at {key_path}")

    from google.auth.transport.requests import Request
    from google.oauth2 import service_account

    creds = service_account.Credentials.from_service_account_file(
        str(key_file),
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    creds.refresh(Request())

    origin = {
        "location": {
            "latLng": {"latitude": waypoints[0]["lat"], "longitude": waypoints[0]["lng"]}
        }
    }
    destination = {
        "location": {
            "latLng": {"latitude": waypoints[-1]["lat"], "longitude": waypoints[-1]["lng"]}
        }
    }
    intermediates = [
        {"location": {"latLng": {"latitude": wp["lat"], "longitude": wp["lng"]}}}
        for wp in waypoints[1:-1]
    ]

    body: dict = {
        "origin": origin,
        "destination": destination,
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_UNAWARE",
        "polylineEncoding": "ENCODED_POLYLINE",
    }
    if intermediates:
        body["intermediates"] = intermediates

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {creds.token}",
        "X-Goog-FieldMask": (
            "routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline,routes.legs"
        ),
    }
    sol_id = solution_id if solution_id is not None else os.environ.get("GMP_SOLUTION_ID", "")
    if sol_id:
        headers["X-Goog-Maps-Solution-ID"] = sol_id

    req = urllib.request.Request(
        ROUTES_API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        res = json.loads(resp.read().decode("utf-8"))

    routes = res.get("routes", [])
    if not routes:
        raise RuntimeError("No route found in Routes API response.")

    return routes[0]


def calculate_optical_budget(distance_meters: float) -> dict:
    """Calculate standard optical link loss at 1310nm/1550nm plus splice budget."""
    if distance_meters < 0:
        raise ValueError("distance_meters must be non-negative.")

    km = distance_meters / 1000.0
    loss_1310 = km * 0.35
    loss_1550 = km * 0.20
    # Standard assumption: 1 splice closure per 2.5 km (0.05 dB per splice)
    num_splices = max(1, int(km / 2.5))
    splicing_loss = num_splices * 0.05
    total_loss_1550 = loss_1550 + splicing_loss

    sop_status = "NORMAL (Within Standard Link Budget)"
    if total_loss_1550 > 24.0:
        sop_status = "CRITICAL (Attenuation Exceeds Transceiver Budget)"
    elif total_loss_1550 > 18.0:
        sop_status = "WARNING (Requires Amplification or Adjusted Split Ratio)"

    return {
        "distance_km": round(km, 2),
        "distance_meters": int(distance_meters),
        "loss_1310_db": round(loss_1310, 2),
        "loss_1550_db": round(loss_1550, 2),
        "est_closures": num_splices,
        "splicing_loss_db": round(splicing_loss, 2),
        "total_budget_1550_db": round(total_loss_1550, 2),
        "sop_status": sop_status,
    }


def _style_tag(style_url: str) -> str:
    if not style_url:
        return ""
    return f"\n\t\t<styleUrl>{escape(style_url)}</styleUrl>"


def inject_route_to_kml(
    kml_path: str,
    route_name: str,
    coords: list[tuple[float, float]],
    waypoints: list[dict],
    distance_meters: float,
    out_path: str | None = None,
    output_kmz: bool = True,
    style_line: str = "",
    style_endpoint: str = "",
    style_waypoint: str = "",
) -> str:
    """Inject a LineString and waypoint Placemarks into a KML copy without mutating input."""
    kml_file = Path(kml_path)
    if not kml_file.exists():
        raise FileNotFoundError(f"KML file not found: {kml_path}")

    target_file = (
        Path(out_path)
        if out_path
        else kml_file.with_name(f"{kml_file.stem}_routed{kml_file.suffix}")
    )

    budget = calculate_optical_budget(distance_meters)
    coord_strings = [f"{lng:.6f},{lat:.6f},0" for lat, lng in coords]
    kml_coordinates = " ".join(coord_strings)

    slug = re.sub(r"[^A-Za-z0-9_]", "_", route_name).upper().strip("_") or "ROUTE"
    safe_name = escape(route_name)

    dist_str = f"{budget['distance_km']} km ({budget['distance_meters']:,} m)"
    budget_str = f"~{budget['total_budget_1550_db']} dB ({budget['sop_status']})"

    placemark_xml = f"""
\t<!-- ================================================================= -->
\t<!-- AUTO-ROUTED: {safe_name} -->
\t<!-- Distance: {budget['distance_km']} km | Loss 1550nm: {budget['total_budget_1550_db']} dB -->
\t<!-- ================================================================= -->
\t<Placemark id="FIBER_LINE_{slug}">
\t\t<name>{safe_name}</name>
\t\t<description><![CDATA[
<b>FTTx Optical Fiber Route</b><br/>
- <b>Cable Length (Snap-to-Road)</b>: {dist_str}<br/>
- <b>Loss @1310nm</b>: ~{budget['loss_1310_db']} dB<br/>
- <b>Loss @1550nm</b>: ~{budget['loss_1550_db']} dB<br/>
- <b>Splicing Budget ({budget['est_closures']} Joint)</b>: ~{budget['splicing_loss_db']} dB<br/>
- <b>Total Link Budget (1550nm)</b>: {budget_str}<br/>
- <i>Generated with fiber-route-kml</i>
]]></description>{_style_tag(style_line)}
\t\t<LineString>
\t\t\t<tessellate>1</tessellate>
\t\t\t<coordinates>
\t\t\t\t{kml_coordinates}
\t\t\t</coordinates>
\t\t</LineString>
\t</Placemark>
"""

    for idx, wp in enumerate(waypoints):
        wp_name = escape(str(wp.get("name", f"Point {idx + 1}")))
        wp_id = f"FIBER_WP_{slug}_{idx + 1}"
        is_endpoint = idx == 0 or idx == len(waypoints) - 1
        wp_style = style_endpoint if is_endpoint else style_waypoint
        wp_desc = f"Route Waypoint: {safe_name} ({wp['lat']:.6f}, {wp['lng']:.6f})"
        placemark_xml += f"""
\t<Placemark id="{wp_id}">
\t\t<name>{wp_name}</name>
\t\t<description><![CDATA[{wp_desc}]]></description>
\t\t<LookAt>
\t\t\t<longitude>{wp['lng']:.6f}</longitude>
\t\t\t<latitude>{wp['lat']:.6f}</latitude>
\t\t\t<altitude>0</altitude>
\t\t\t<range>500</range>
\t\t\t<altitudeMode>relativeToSeaFloor</altitudeMode>
\t\t</LookAt>{_style_tag(wp_style)}
\t\t<Point>
\t\t\t<coordinates>{wp['lng']:.6f},{wp['lat']:.6f},0</coordinates>
\t\t</Point>
\t</Placemark>
"""

    content = kml_file.read_text(encoding="utf-8")
    doc_end_idx = content.rfind("</Document>")
    if doc_end_idx == -1:
        raise ValueError("Could not find </Document> tag in target KML")

    updated_content = content[:doc_end_idx] + placemark_xml + content[doc_end_idx:]
    ET.fromstring(updated_content.encode("utf-8"))
    target_file.write_text(updated_content, encoding="utf-8")

    if output_kmz:
        kmz_path = target_file.with_suffix(".kmz")
        with zipfile.ZipFile(str(kmz_path), "w", zipfile.ZIP_DEFLATED) as zipf:
            zipf.writestr("doc.kml", updated_content.encode("utf-8"))

    return str(target_file)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="FTTx Optical Fiber Route KML/KMZ Generator"
    )
    parser.add_argument("--url", required=True, help="Google Maps directions URL")
    parser.add_argument("--kml", required=True, help="Path to base KML file")
    parser.add_argument("--out", default=None, help="Output KML path (default: <kml>_routed.kml)")
    parser.add_argument("--name", default="FTTx Fiber Route", help="LineString placemark name")
    parser.add_argument(
        "--key",
        default=None,
        help="Path to GCP Service Account JSON (or set GOOGLE_APPLICATION_CREDENTIALS)",
    )
    parser.add_argument(
        "--solution-id",
        default=None,
        help="Optional Google Maps Platform solution ID header",
    )
    parser.add_argument("--no-kmz", action="store_true", help="Skip generating .kmz archive")

    args = parser.parse_args(argv)

    print(f"[*] Resolving Google Maps URL: {args.url}")
    waypoints = resolve_maps_url(args.url)
    print(f"[*] Detected {len(waypoints)} waypoints:")
    for wp in waypoints:
        print(f"    - {wp['name']}: {wp['lat']}, {wp['lng']}")

    print("[*] Computing snap-to-road route via Google Routes API...")
    route_data = compute_route_snap_to_road(
        waypoints,
        sa_key_path=args.key,
        solution_id=args.solution_id,
    )
    dist_m = route_data.get("distanceMeters", 0)
    poly = route_data["polyline"]["encodedPolyline"]
    coords = decode_polyline(poly)

    budget = calculate_optical_budget(dist_m)
    print("[+] Route computed:")
    print(f"    Distance      : {budget['distance_km']} km ({budget['distance_meters']:,} m)")
    print(f"    Coordinates   : {len(coords)} points")
    print(f"    Loss @1550nm  : ~{budget['total_budget_1550_db']} dB ({budget['sop_status']})")

    out_path = inject_route_to_kml(
        args.kml,
        args.name,
        coords,
        waypoints,
        dist_m,
        out_path=args.out,
        output_kmz=not args.no_kmz,
    )
    print(f"[+] Saved routed KML to: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
