import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest
from fiber_route_kml import (
    calculate_optical_budget,
    decode_polyline,
    inject_route_to_kml,
)

BASE_KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
  <name>Sample FTTx Network</name>
</Document>
</kml>
"""


def test_decode_polyline_google_reference() -> None:
    # Standard Google Encoded Polyline Algorithm reference example
    encoded = "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
    coords = decode_polyline(encoded)
    assert len(coords) == 3
    assert coords[0] == pytest.approx((38.5, -120.2), abs=1e-5)
    assert coords[1] == pytest.approx((40.7, -120.95), abs=1e-5)
    assert coords[2] == pytest.approx((43.252, -126.453), abs=1e-5)


def test_decode_polyline_empty() -> None:
    assert decode_polyline("") == []


def test_calculate_optical_budget_normal() -> None:
    budget = calculate_optical_budget(5000)
    assert budget["distance_km"] == 5.0
    assert budget["distance_meters"] == 5000
    assert budget["loss_1310_db"] == 1.75
    assert budget["loss_1550_db"] == 1.0
    assert budget["est_closures"] == 2
    assert budget["splicing_loss_db"] == 0.1
    assert budget["total_budget_1550_db"] == 1.1
    assert budget["sop_status"].startswith("NORMAL")


def test_calculate_optical_budget_thresholds() -> None:
    warning = calculate_optical_budget(90000)  # 90 km -> ~19.8 dB @1550nm
    assert warning["sop_status"].startswith("WARNING")

    critical = calculate_optical_budget(120000)  # 120 km -> ~26.4 dB @1550nm
    assert critical["sop_status"].startswith("CRITICAL")


def test_calculate_optical_budget_negative_raises() -> None:
    with pytest.raises(ValueError):
        calculate_optical_budget(-10)


def test_inject_route_to_kml_writes_output_without_mutating_input(tmp_path: Path) -> None:
    src_kml = tmp_path / "base.kml"
    src_kml.write_text(BASE_KML, encoding="utf-8")
    out_kml = tmp_path / "out.kml"

    result_path = inject_route_to_kml(
        kml_path=str(src_kml),
        route_name="Backbone North-01",
        coords=[(-6.2, 106.8), (-6.21, 106.82)],
        waypoints=[
            {"lat": -6.2, "lng": 106.8, "name": "POP-A"},
            {"lat": -6.21, "lng": 106.82, "name": "ODP-B"},
        ],
        distance_meters=2500,
        out_path=str(out_kml),
        output_kmz=True,
    )

    assert Path(result_path) == out_kml
    assert src_kml.read_text(encoding="utf-8") == BASE_KML

    out_text = out_kml.read_text(encoding="utf-8")
    assert 'id="FIBER_LINE_BACKBONE_NORTH_01"' in out_text
    assert 'id="FIBER_WP_BACKBONE_NORTH_01_1"' in out_text
    assert 'id="FIBER_WP_BACKBONE_NORTH_01_2"' in out_text
    ET.fromstring(out_text.encode("utf-8"))

    kmz_path = out_kml.with_suffix(".kmz")
    assert kmz_path.exists()
    with zipfile.ZipFile(kmz_path, "r") as zf:
        assert "doc.kml" in zf.namelist()
        ET.fromstring(zf.read("doc.kml"))
