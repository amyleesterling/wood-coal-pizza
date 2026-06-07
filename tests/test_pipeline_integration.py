"""End-to-end test on the bundled offline sample (no network)."""
from wcpizza.config import load_config
from wcpizza.pipeline import run_pipeline


def test_sample_pipeline_runs_and_new_haven_wins(tmp_path):
    cfg = load_config()
    # Redirect outputs to a temp dir so the test doesn't touch the repo.
    cfg.data["run"]["processed_dir"] = str(tmp_path)

    meta = run_pipeline(cfg, source="sample", states=[])

    assert meta["raw_records"] > 0
    # Frank Pepe appears twice (node + way) and must be deduped away.
    assert meta["deduped_records"] < meta["raw_records"]
    assert meta["cities_ranked"] >= 3

    import csv
    with open(tmp_path / "ranking.csv", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    assert rows, "ranking should not be empty"
    # New Haven (small population, many coal-fired apizza) should top per-capita.
    assert rows[0]["city_display"].lower().startswith("new haven")
    # Stamford has only one wood-fired pizzeria -> filtered out by min_restaurants.
    assert all("stamford" not in r["city_display"].lower() for r in rows)
