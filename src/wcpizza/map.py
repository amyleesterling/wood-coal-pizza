"""Render an interactive HTML map of pizzerias, colored by oven type.

Produces a single self-contained HTML file that uses Leaflet + the MarkerCluster
plugin (loaded from CDNs) and embeds the restaurant points as GeoJSON. No build
step, no Python plotting dependencies — open the file in any browser.

Features:
  * One circle marker per pizzeria, colored by oven classification.
  * Marker clustering so thousands of points stay responsive.
  * A layer toggle per oven category and a legend with live counts.
  * Popups with name, city, classification, confidence, evidence, and website.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

# Oven label -> (display name, marker color).
CATEGORY_STYLE = {
    "coal": ("Coal-fired", "#1a1a1a"),
    "wood": ("Wood-fired", "#d7301f"),
    "wood_or_coal": ("Wood/coal (ambiguous)", "#8c510a"),
    "gas_electric": ("Gas / electric", "#4575b4"),
    "unknown": ("Unknown", "#9e9e9e"),
}
_DEFAULT_STYLE = ("Other", "#9e9e9e")


def _to_feature(rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        lat = float(rec["lat"])
        lon = float(rec["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    label = rec.get("oven_label") or "unknown"
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "name": rec.get("name") or "(unnamed)",
            "city": rec.get("city_display") or rec.get("addr_city") or "",
            "state": rec.get("state") or rec.get("addr_state") or "",
            "label": label,
            "confidence": rec.get("oven_confidence"),
            "evidence": rec.get("oven_evidence") or "",
            "website": rec.get("website") or "",
        },
    }


def _js_json(obj: Any) -> str:
    """Serialize to JSON safe to embed inside an HTML <script> block.

    Escapes the characters that could prematurely close the script element or
    break parsing (`<`, `>`, `&`, and the JS line separators U+2028/U+2029).
    """
    return (
        json.dumps(obj, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def build_map_html(restaurants: List[Dict[str, Any]], *,
                   title: str = "Wood/Coal-Fired Pizza Map") -> str:
    """Return a self-contained HTML document plotting the restaurants."""
    features = [f for f in (_to_feature(r) for r in restaurants) if f]

    counts: Dict[str, int] = {}
    sum_lat = sum_lon = 0.0
    for f in features:
        counts[f["properties"]["label"]] = counts.get(f["properties"]["label"], 0) + 1
        lon, lat = f["geometry"]["coordinates"]
        sum_lat += lat
        sum_lon += lon
    n = len(features) or 1
    center = [sum_lat / n, sum_lon / n] if features else [39.5, -98.35]

    return _TEMPLATE.format(
        title=_js_json(title),
        center=_js_json(center),
        data=_js_json({"type": "FeatureCollection", "features": features}),
        styles=_js_json(CATEGORY_STYLE),
        counts=_js_json(counts),
        total=len(features),
    )


def write_map(path: str | Path, restaurants: List[Dict[str, Any]],
              *, title: str = "Wood/Coal-Fired Pizza Map") -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_map_html(restaurants, title=title), encoding="utf-8")
    return path


# The {{ }} are literal braces for CSS/JS; .format() fills {title}, {center},
# {data}, {styles}, {counts}, {total}.
_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Wood/Coal-Fired Pizza Map</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css" />
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css" />
<style>
  html, body {{ height: 100%; margin: 0; }}
  #map {{ height: 100%; width: 100%; }}
  .legend {{ background: white; padding: 8px 10px; border-radius: 6px;
            box-shadow: 0 1px 5px rgba(0,0,0,.3); font: 13px/1.4 sans-serif; }}
  .legend h4 {{ margin: 0 0 6px; font-size: 13px; }}
  .legend .row {{ display: flex; align-items: center; margin: 2px 0; }}
  .legend .dot {{ width: 12px; height: 12px; border-radius: 50%;
                 margin-right: 6px; border: 1px solid #555; }}
  .legend .total {{ margin-top: 6px; color: #555; }}
  .popup b {{ font-size: 14px; }}
  .popup .ev {{ color: #555; font-size: 12px; }}
</style>
</head>
<body>
<div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
<script>
  var TITLE = {title};
  var CENTER = {center};
  var STYLES = {styles};
  var COUNTS = {counts};
  var TOTAL = {total};
  var DATA = {data};

  var map = L.map("map").setView(CENTER, TOTAL > 0 ? 6 : 4);
  L.tileLayer("https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", {{
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors (ODbL)'
  }}).addTo(map);

  function styleFor(label) {{ return STYLES[label] || ["Other", "#9e9e9e"]; }}

  function esc(s) {{
    return String(s == null ? "" : s)
      .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
  }}

  // One clustered layer per oven category, so the layer control filters them.
  var layers = {{}};
  Object.keys(STYLES).forEach(function(key) {{
    layers[key] = L.markerClusterGroup({{ chunkedLoading: true }});
  }});

  DATA.features.forEach(function(f) {{
    var p = f.properties;
    var c = f.geometry.coordinates;
    var st = styleFor(p.label);
    var marker = L.circleMarker([c[1], c[0]], {{
      radius: 6, color: "#333", weight: 1,
      fillColor: st[1], fillOpacity: 0.85
    }});
    var conf = (p.confidence == null) ? "" : " (conf " + p.confidence + ")";
    var site = p.website
      ? '<br><a href="' + esc(p.website) + '" target="_blank" rel="noopener">website</a>'
      : "";
    var ev = p.evidence ? '<div class="ev">' + esc(p.evidence) + '</div>' : "";
    marker.bindPopup(
      '<div class="popup"><b>' + esc(p.name) + '</b><br>' +
      esc([p.city, p.state].filter(Boolean).join(", ")) + '<br>' +
      '<b>' + esc(st[0]) + '</b>' + esc(conf) + ev + site + '</div>'
    );
    (layers[p.label] || layers["unknown"]).addLayer(marker);
  }});

  var overlays = {{}};
  Object.keys(layers).forEach(function(key) {{
    var st = styleFor(key);
    var count = COUNTS[key] || 0;
    if (count === 0) return;
    map.addLayer(layers[key]);
    overlays['<span style="color:' + st[1] + '">&#9679;</span> ' +
             st[0] + ' (' + count + ')'] = layers[key];
  }});
  L.control.layers(null, overlays, {{ collapsed: false }}).addTo(map);

  var legend = L.control({{ position: "bottomright" }});
  legend.onAdd = function() {{
    var div = L.DomUtil.create("div", "legend");
    var html = "<h4>" + esc(TITLE) + "</h4>";
    Object.keys(STYLES).forEach(function(key) {{
      var st = STYLES[key], count = COUNTS[key] || 0;
      if (count === 0) return;
      html += '<div class="row"><span class="dot" style="background:' +
        st[1] + '"></span>' + esc(st[0]) + ' &middot; ' + count + '</div>';
    }});
    html += '<div class="total">' + TOTAL + ' pizzerias mapped</div>';
    div.innerHTML = html;
    return div;
  }};
  legend.addTo(map);
</script>
</body>
</html>
"""
