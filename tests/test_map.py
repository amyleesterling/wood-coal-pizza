from wcpizza.map import build_map_html


def _rec(name, lat, lon, label, conf=0.9):
    return {"name": name, "lat": lat, "lon": lon, "oven_label": label,
            "oven_confidence": conf, "city_display": "Testville",
            "state": "CT", "oven_evidence": "coal:'coal fired'",
            "website": "http://example.com"}


def test_build_map_html_contains_points_and_legend():
    recs = [
        _rec("Frank Pepe", 41.30, -72.92, "coal"),
        _rec("Bianco", 33.45, -112.07, "wood"),
        _rec("Mystery Slice", 40.71, -74.0, "unknown"),
    ]
    html = build_map_html(recs, title="My Map")
    assert "<!DOCTYPE html>" in html
    assert "leaflet" in html.lower()
    # Data is embedded as GeoJSON.
    assert "FeatureCollection" in html
    assert "Frank Pepe" in html
    assert "My Map" in html
    # Coordinates are embedded (GeoJSON is lon,lat).
    assert "-72.92" in html
    # Total is embedded as a JS var; the legend text is built client-side.
    assert "var TOTAL = 3;" in html


def test_handles_missing_coordinates_gracefully():
    recs = [
        _rec("Good", 41.0, -72.0, "wood"),
        {"name": "Bad", "oven_label": "coal"},  # no lat/lon -> skipped
    ]
    html = build_map_html(recs)
    assert "Good" in html
    assert "var TOTAL = 1;" in html


def test_empty_input_still_valid_html():
    html = build_map_html([])
    assert "<!DOCTYPE html>" in html
    assert "var TOTAL = 0;" in html


def test_html_escaping_of_names():
    recs = [{"name": "Tony & <script>", "lat": 1.0, "lon": 1.0,
             "oven_label": "wood"}]
    html = build_map_html(recs)
    # Raw <script> must not appear unescaped inside the embedded JS data.
    assert "Tony & <script>" not in html
    assert "\\u003c" in html and "\\u0026" in html
