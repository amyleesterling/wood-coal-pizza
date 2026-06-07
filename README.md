# wood-coal-pizza 🍕🔥

A small, **reproducible, public-data-only** Python pipeline that estimates
**which U.S. city has the most wood/coal-fired pizza restaurants per capita.**

It pulls pizzeria locations from **OpenStreetMap** (via the sanctioned Overpass
API) and city populations from the **U.S. Census Bureau API**, deduplicates the
restaurants, classifies each one's **oven type** from its name / description /
tags (and, optionally, its own website), and computes a **per-capita ranking**.

```
 OpenStreetMap (Overpass) ┐
                          ├─►  dedupe  ─►  classify oven  ─►  rank per capita  ─►  CSV + JSON
 U.S. Census (population) ┘
```

> **Why these sources?** Both are open and meant to be queried programmatically
> — OSM data is ODbL-licensed and the Overpass API is a documented query
> endpoint (not screen-scraping); Census data is U.S. public domain. We do **no
> prohibited scraping**: no Google/Yelp scraping, no bypassing terms. Optional
> website enrichment fetches only a restaurant's *own* homepage and honors
> `robots.txt`. See [METHODOLOGY.md](METHODOLOGY.md).

---

## Quick start

```bash
# 1. Install (Python 3.9+)
make dev          # or: pip install -r requirements-dev.txt

# 2. Run the tests
make test

# 3. Run OFFLINE on the bundled sample data (no network needed)
make sample

# 4. Run LIVE against the real APIs for the states you care about
make run STATES=NY,NJ,CT,MA,RI,PA   # hits Overpass + Census
```

Live runs are scoped by U.S. state (the natural unit for both Overpass area
queries and the Census place endpoint). Add more states for broader coverage;
the public Overpass instance is rate-limited, so the pipeline pauses between
requests and caches every response under `.http_cache/` for reproducibility.

A free [Census API key](https://api.census.gov/data/key_signup.html) is
recommended for live runs:

```bash
export CENSUS_API_KEY=your_key_here
```

## Output

Written to `data/processed/`:

| File | Contents |
|------|----------|
| `ranking.csv` | City-level per-capita ranking (the headline result) |
| `restaurants.csv` | Every deduped pizzeria with its oven classification + evidence |
| `map.html` | Interactive Leaflet map of every pizzeria, colored by oven type |
| `summary.json` | Run metadata: record counts, parameters, top cities |

The committed `*_sample.csv` / `*_sample.json` files are the output of
`make sample`, so you can see the format without running anything.

### Demonstration result (bundled sample data)

`make sample` runs on a small **synthetic** fixture (not a real extract) that
includes the usual suspects. The ranking it produces:

| rank | city | wood/coal | population | raw /100k | shrunk /100k |
|-----:|------|----------:|-----------:|----------:|-------------:|
| 1 | New Haven, CT | 5 | 134,023 | 3.73 | 0.316 |
| 2 | Portland, OR | 3 | 652,503 | 0.46 | 0.217 |
| 3 | Boston, MA | 3 | 654,776 | 0.46 | 0.217 |
| 4 | Phoenix, AZ | 3 | 1,608,139 | 0.19 | 0.172 |
| 5 | New York, NY | 4 | 8,336,817 | 0.05 | 0.079 |

New Haven — the home of coal-fired *apizza* — tops the list on both the raw and
the shrinkage-adjusted rate, which is exactly the kind of robust, defensible
finding the methodology is designed to surface. **This is illustrative only;
run live for a real answer.**

## How it works

| Stage | Module | What it does |
|-------|--------|--------------|
| Fetch | `sources/osm.py`, `sources/census.py` | Cached Overpass + Census API calls |
| Dedupe | `dedupe.py` | Collapse records within 75 m **and** ~0.87 name similarity (spatial grid + union-find) |
| Classify | `classify.py` | Label oven as `coal` / `wood` / `wood_or_coal` / `gas_electric` / `unknown` with a confidence and **auditable evidence** |
| Enrich (opt.) | `sources/website.py` | robots.txt-respecting homepage text to improve classification |
| Rank | `rank.py` | Per-capita rate with count/population floors + empirical-Bayes shrinkage |
| Orchestrate | `pipeline.py` | CLI (`wcpizza run …`) wiring it all together |

Everything that affects the result lives in [`config.yaml`](config.yaml), so a
run is fully described by *(code version + config + cached snapshots)*.

## CLI

```bash
wcpizza run --source sample            # offline demo
wcpizza run --source live --states NY,NJ
wcpizza fetch --states NY              # only fetch + cache raw sources
wcpizza map --input data/processed/restaurants.csv --out map.html  # (re)build the map
wcpizza --config myconfig.yaml run ... # override configuration
```

## Interactive map

Every run writes a self-contained `map.html` (Leaflet + MarkerCluster, no build
step) plotting all pizzerias, colored by oven type, with per-category toggles, a
legend, and popups showing the classification evidence. Open it in any browser,
or rebuild it from a previous run's CSV with `wcpizza map`.

## Running without local network access (GitHub Actions)

If the machine you're on can't reach Overpass/Census (a locked-down sandbox,
say), run the pipeline on a GitHub-hosted runner instead — runners have open
outbound internet. `.github/workflows/live-ranking.yml` runs the live pipeline
for all 50 states + DC, commits `results/` (map + ranking + restaurants) back to
the branch, and uploads them as an artifact. It uses the **keyless** Census
population file by default; set a `CENSUS_API_KEY` repo secret to use the API
instead. An accumulating HTTP cache keeps re-runs from re-hammering Overpass.

`.github/workflows/tests.yml` runs the test suite on every push/PR.

### Oven-type recall, and how to improve it

In real OSM data only ~1% of pizzerias carry an explicit `oven` tag or a
name/description that names the fuel, so most land in `unknown`. Two levers
raise recall: enable website enrichment (`classify.use_website_text: true`,
which reads each pizzeria's own homepage, robots-respecting and capped/
concurrent), and lower `classify.min_confidence`. See METHODOLOGY.md §7–8.

## Caveats

This is an **estimate**, and the answer depends on coverage, classification
precision, and how you define "city" and "per capita". The
[methodology](METHODOLOGY.md) spells out the assumptions, known biases (OSM
completeness varies by region; `addr:city` is sparse), and how to harden the
pipeline (point-in-polygon city assignment via Census TIGER, website
enrichment, Wikidata cross-checks). Read it before quoting a winner.

## License

Code: MIT (see [LICENSE](LICENSE)). Data: OpenStreetMap © OpenStreetMap
contributors (ODbL) — **attribution required**; U.S. Census data is public
domain.
