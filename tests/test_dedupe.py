from wcpizza.dedupe import dedupe
from wcpizza.utils import haversine_m


def test_haversine_known_distance():
    # ~1.11 km per 0.01 deg latitude.
    d = haversine_m(40.0, -73.0, 40.01, -73.0)
    assert 1100 < d < 1120


def test_collapses_node_and_way_duplicate():
    records = [
        {"id": "osm:node/1", "name": "Frank Pepe Pizzeria", "lat": 41.3052,
         "lon": -72.9270, "tags": {"oven": "coal"}},
        {"id": "osm:way/2", "name": "Frank Pepe Pizzeria", "lat": 41.30521,
         "lon": -72.92702, "tags": {}},
    ]
    out = dedupe(records, distance_m=75, name_similarity=0.87)
    assert len(out) == 1
    assert out[0]["dup_count"] == 2
    # Representative should be the richer record (has the oven tag).
    assert out[0]["tags"].get("oven") == "coal"


def test_does_not_merge_far_apart_same_name():
    records = [
        {"id": "a", "name": "Joe's Pizza", "lat": 40.0, "lon": -73.0, "tags": {}},
        {"id": "b", "name": "Joe's Pizza", "lat": 41.0, "lon": -73.0, "tags": {}},
    ]
    out = dedupe(records, distance_m=75)
    assert len(out) == 2


def test_does_not_merge_different_names_same_spot():
    records = [
        {"id": "a", "name": "Frank Pepe", "lat": 40.0, "lon": -73.0, "tags": {}},
        {"id": "b", "name": "Sally's Apizza", "lat": 40.00001, "lon": -73.0,
         "tags": {}},
    ]
    out = dedupe(records, distance_m=75)
    assert len(out) == 2


def test_empty_input():
    assert dedupe([]) == []


def test_deterministic_ordering():
    records = [
        {"id": "z", "name": "A", "lat": 1.0, "lon": 1.0, "tags": {}},
        {"id": "a", "name": "B", "lat": 2.0, "lon": 2.0, "tags": {}},
    ]
    out1 = dedupe(records)
    out2 = dedupe(list(reversed(records)))
    assert [r["id"] for r in out1] == [r["id"] for r in out2]
