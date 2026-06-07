from wcpizza.rank import aggregate_counts, rank


def _restaurant(city, state, label, conf=0.95):
    return {"city_norm": city, "state": state, "city_display": city.title(),
            "oven_label": label, "oven_confidence": conf}


def test_aggregate_counts_respects_confidence():
    recs = [
        _restaurant("new haven", "CT", "coal", 0.95),
        _restaurant("new haven", "CT", "wood_or_coal", 0.3),  # below min_conf
        _restaurant("new haven", "CT", "gas_electric", 0.99),
    ]
    agg = aggregate_counts(recs, min_confidence=0.5)
    key = ("new haven", "CT")
    assert agg[key]["wood_coal"] == 1
    assert agg[key]["total_pizzerias"] == 3


def test_rank_small_city_beats_big_city_per_capita():
    recs = (
        [_restaurant("new haven", "CT", "coal") for _ in range(5)]
        + [_restaurant("new york", "NY", "coal") for _ in range(8)]
    )
    pop = {
        ("new haven", "CT"): {"population": 134000, "place_display": "New Haven", "geoid": "0952000"},
        ("new york", "NY"): {"population": 8336817, "place_display": "New York", "geoid": "3651000"},
    }
    out = rank(recs, pop, min_restaurants=3, min_population=20000, shrinkage_k=0)
    assert out[0]["city_display"] == "New Haven"
    assert out[0]["rank"] == 1
    assert out[0]["raw_per_100k"] > out[1]["raw_per_100k"]


def test_min_restaurants_filter():
    recs = [_restaurant("tiny", "CT", "wood") for _ in range(2)]
    pop = {("tiny", "CT"): {"population": 50000, "place_display": "Tiny", "geoid": "1"}}
    out = rank(recs, pop, min_restaurants=3)
    assert out == []


def test_min_population_filter():
    recs = [_restaurant("village", "VT", "wood") for _ in range(5)]
    pop = {("village", "VT"): {"population": 5000, "place_display": "Village", "geoid": "1"}}
    out = rank(recs, pop, min_restaurants=3, min_population=20000)
    assert out == []


def test_shrinkage_pulls_small_city_toward_prior():
    # One small city with a high raw rate, one large city defining the prior.
    recs = (
        [_restaurant("small", "CT", "coal") for _ in range(3)]
        + [_restaurant("big", "NY", "coal") for _ in range(50)]
    )
    pop = {
        ("small", "CT"): {"population": 30000, "place_display": "Small", "geoid": "1"},
        ("big", "NY"): {"population": 5000000, "place_display": "Big", "geoid": "2"},
    }
    no_shrink = rank(recs, pop, min_restaurants=3, shrinkage_k=0)
    shrink = rank(recs, pop, min_restaurants=3, shrinkage_k=10)
    small_raw = next(r for r in no_shrink if r["city_display"] == "Small")["raw_per_100k"]
    small_shrunk = next(r for r in shrink if r["city_display"] == "Small")["shrunk_per_100k"]
    assert small_shrunk < small_raw  # pulled down toward the (lower) prior


def test_unmatched_city_dropped():
    recs = [_restaurant("nowhere", "ZZ", "wood") for _ in range(5)]
    out = rank(recs, {}, min_restaurants=3)
    assert out == []
