# fiber-route-kml

> FTTx optical fiber route KML/KMZ generator with 1310/1550 nm optical link budget calculation.

**fiber-route-kml** takes a Google Maps directions URL, snaps waypoints to real road geometry via the Google Maps Platform Routes API, calculates 1310 nm / 1550 nm attenuation and splice budgets, and writes a non-destructive KML + KMZ overlay ready for Google Earth.

## Features

- Resolves `maps.app.goo.gl` shortlinks and full Google Maps `/dir/` URLs into waypoints
- Calls `routes.googleapis.com/directions/v2:computeRoutes` (`DRIVE` snap-to-road)
- Decodes encoded polylines into `(lat, lng)` coordinates
- Computes FTTx optical link budget (`0.35 dB/km @1310nm`, `0.20 dB/km @1550nm`, plus `0.05 dB` per 2.5 km splice closure) with `NORMAL` / `WARNING` / `CRITICAL` thresholds
- Injects `FIBER_LINE_*` (`LineString`) and `FIBER_WP_*` (`Point`) placemarks into a new KML copy (`--out`) and packages a `.kmz` archive without mutating the source file

## Installation

```bash
git clone https://github.com/gas-gatrapurna/fiber-route-kml.git
cd fiber-route-kml
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[google,dev]"
```

Offline functions (`decode_polyline`, `calculate_optical_budget`, `inject_route_to_kml`) require **zero external dependencies** (`pip install -e .`).

## Usage

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/gcp-service-account.json
fiber-route-kml \
  --url "https://maps.google.com/maps/dir/..." \
  --kml ./base-network.kml \
  --out ./base-network-routed.kml \
  --name "Backbone Sector North"
```

## Development

```bash
ruff check src tests
pytest -v
```

## License

MIT
