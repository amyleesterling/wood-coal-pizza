from wcpizza.classify import classify


def test_osm_oven_tag_wins():
    c = classify(name="Some Pizza", osm_tags={"oven": "wood"})
    assert c.label == "wood"
    assert c.confidence > 0.9
    assert any("osm:oven" in e for e in c.evidence)


def test_osm_coal_tag():
    c = classify(name="X", osm_tags={"oven": "coal"})
    assert c.label == "coal"


def test_strong_coal_in_name():
    c = classify(name="Tony's Coal Fired Pizza")
    assert c.label == "coal"
    assert c.confidence >= 0.9


def test_strong_wood_in_description():
    c = classify(name="Bianco", description="Wood fired Neapolitan pizza")
    assert c.label == "wood"
    assert c.confidence >= 0.9


def test_conventional_excluded():
    c = classify(name="Joe's", osm_tags={"oven": "gas"})
    assert c.label == "gas_electric"
    assert not c.is_wood_or_coal


def test_gas_keyword_only():
    c = classify(name="Fast Pizza", description="gas fired conveyor oven")
    assert c.label == "gas_electric"
    assert not c.is_wood_or_coal


def test_ambiguous_brick_oven_low_confidence():
    c = classify(name="Regina", description="Classic brick oven pizza")
    assert c.label == "wood_or_coal"
    assert c.confidence < 0.6  # not conclusive enough to count by default


def test_unknown_when_no_signal():
    c = classify(name="Generic Slice Shop", description="cheap slices")
    assert c.label == "unknown"
    assert c.confidence == 0.0


def test_both_wood_and_coal_named():
    # Both contiguous phrases present and roughly tied -> ambiguous fuel.
    c = classify(name="Wood Fired & Coal Fired Pizza Co")
    assert c.label == "wood_or_coal"


def test_accent_and_italian_legna():
    c = classify(name="Forno a Legna", description="pizza")
    assert c.label == "wood"
    assert c.is_wood_or_coal
