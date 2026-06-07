# Methodology

This document describes how the pipeline estimates **wood/coal-fired pizza
restaurants per capita** by U.S. city, the assumptions and biases involved, the
licensing/ethics of the data, and how to harden the estimate. The goal is a
result that is **reproducible** (anyone re-running the code with the same config
gets the same answer) and **auditable** (every classification carries its
evidence).

## 1. Question and definitions

> *Which U.S. city has the most wood/coal-fired pizza restaurants per capita?*

Operationalized as:

- **Restaurant**: a food-service POI (`amenity=restaurant|fast_food|cafe`) that
  is pizza-related (cuisine contains `pizza`, or the name contains `pizz`).
- **Wood/coal-fired**: the oven is fueled by wood or coal (solid fuel), as
  opposed to gas, electric, or conveyor/deck ovens. We keep three positive
  labels — `coal`, `wood`, and `wood_or_coal` (solid fuel, fuel not
  disambiguated).
- **City**: a U.S. Census **"place"** (incorporated places + census designated
  places). This is the unit closest to colloquial "city" and is the one the
  Census population API exposes. (Caveat: places ≠ metro areas; see §7.)
- **Per capita**: wood/coal restaurants per 100,000 residents.

## 2. Data sources (public only, no prohibited scraping)

| Source | What | License | Access |
|--------|------|---------|--------|
| **OpenStreetMap** via **Overpass API** | Restaurant POIs, names, addresses, websites, and any `oven`/`fuel` tags | ODbL (attribution required) | Overpass is a documented, sanctioned **query API** — not website scraping |
| **U.S. Census Bureau Data API** | City ("place") total population (ACS 5-year, `B01003_001E`) | U.S. public domain | Official JSON API |
| *(optional)* a restaurant's **own website** | Free-text oven description | the site's own content | One homepage only, **robots.txt honored**, off by default |

**What we deliberately do *not* do:** scrape Google Maps / Yelp / TripAdvisor or
any source whose terms forbid automated collection; bypass paywalls, CAPTCHAs,
or rate limits; or fetch third-party pages. The optional website enrichment
(`sources/website.py`) fetches only the restaurant's *own* homepage, checks
`robots.txt` for our User-Agent first, caps extracted text, caches, and fails
closed (returns nothing on any doubt). It is **disabled by default**.

We are good API citizens: a descriptive `User-Agent`, a configurable delay
between Overpass requests, and an on-disk response cache so re-runs don't re-hit
upstream services. For large national runs, self-host an Overpass instance.

## 3. Pipeline stages

```
fetch (OSM + Census)  →  dedupe  →  assign city  →  classify oven  →  rank
```

### 3.1 Fetch
Per state: one Overpass area query for pizza POIs, one Census `place:*` query
for populations. Both responses are cached by a hash of the request, making the
run deterministic. State is the unit because Overpass area queries and the
Census place endpoint are both naturally state-scoped.

### 3.2 Deduplicate (`dedupe.py`)
The same restaurant can appear multiple times — as an OSM node *and* a building
way/relation, across refreshes, or across sources. Two records merge iff they
are **both**:
- within `dedupe.distance_m` (default **75 m**) — great-circle (haversine), and
- have normalized-name similarity ≥ `dedupe.name_similarity` (default **0.87**,
  `difflib` ratio on a stop-word-stripped, de-accented key).

We bucket points into a spatial grid sized to the distance threshold and only
compare within a 3×3 neighborhood (near-linear instead of O(n²)), then form
clusters with union-find. The cluster's **representative** is the richest record
(prefers an explicit `oven` tag, then a website, then most tags), and we record
`dup_count` and the merged `source_ids` for transparency.

Requiring *both* proximity and name similarity avoids the two classic failure
modes: merging two different restaurants in the same plaza, and failing to merge
the node+footprint of one restaurant.

### 3.3 Assign city
Each restaurant is mapped to a (city, state) from its OSM `addr:city` /
`addr:state` tags, normalized to join against Census place names (strip the
trailing state, drop suffixes like " city"/" town"/" CDP", de-accent,
lowercase). `addr:state` accepts both `NY` and `New York`.

> **Known limitation:** `addr:city` is not always present in OSM, and a POI's
> stated city may differ from the place polygon it falls in. The robust upgrade
> is point-in-polygon assignment against Census **TIGER/Line place** boundaries
> (see §8). We chose tag-based assignment to keep the default dependency
> footprint to the standard library; the bias is documented and measurable
> (count records dropped for a missing/unmatched city in `restaurants.csv`).

### 3.4 Classify oven type (`classify.py`)
Signals, in priority order:
1. **Explicit OSM tags** `oven`/`fuel`/`oven:fuel` (`wood`, `coal`, `charcoal`,
   `gas`, `electric`). A mapper asserted these, so they dominate (confidence
   ≈ 0.95–0.97).
2. **Strong keyword phrases** in name/description/cuisine (and website text if
   enabled): e.g. `coal fired`, `coal oven`, `anthracite` → **coal**;
   `wood fired`, `wood burning`, `forno a legna`, `legna` → **wood**.
3. **Ambiguous solid-fuel** phrases (`brick oven`, `stone oven`, `hearth`,
   `forno`) → **wood_or_coal** at low confidence — these *suggest* solid fuel
   but don't prove it.
4. **Wood-leaning** context (`Neapolitan`, `VPN certified`, `900 degrees`) adds
   weight to wood.
5. **Conventional** phrases (`gas fired`, `electric oven`, `conveyor`) are a
   negative signal and can label a POI `gas_electric` (excluded).

Each result carries a **label**, a **confidence in [0, 1]**, and the **evidence**
(which phrases/tags fired), all written to `restaurants.csv`. Only positive
labels with confidence ≥ `classify.min_confidence` (default **0.5**) count
toward the ranking — so a bare "brick oven" mention (≈0.45) does *not* count
unless corroborated. This is a **precision-over-recall** default; lower the
threshold for more recall.

> This is a transparent rules classifier, not an ML model: it's debuggable,
> needs no labeled training data, and every decision is explainable. Its
> precision/recall can be measured against a hand-labeled sample and tuned via
> the keyword tables and threshold.

### 3.5 Rank per capita (`rank.py`)
For each matched (city, state): count positive restaurants, divide by Census
population, scale to per 100,000.

Naive per-capita rates are dominated by tiny places (one pizzeria in a 5,000-
person town = a huge rate), so we apply:

- **Hard floors:** `rank.min_restaurants` (default 3) and `rank.min_population`
  (default 20,000) suppress small-sample noise.
- **Empirical-Bayes shrinkage:** we shrink each city's rate toward the national
  rate by adding a pseudo-population that would, at the national rate, yield
  `rank.shrinkage_k` restaurants:

  ```
  prior_rate   = total_wood_coal / total_population        # national, per person
  alpha_pop    = shrinkage_k / prior_rate                  # pseudo-population
  shrunk_/100k = (wood_coal + shrinkage_k) / (population + alpha_pop) * 100000
  ```

  This is the standard "Bayesian average" used for ratings: small cities are
  pulled strongly toward the national rate (you need more evidence to believe an
  extreme rate from little data), while large cities are essentially unchanged.
  Because the national base rate is low, the shrinkage is intentionally
  conservative — a city that still leads *after* shrinkage (as New Haven does in
  the sample) is a genuinely robust result.

The headline ranking sorts by `shrunk_per_100k`, but `raw_per_100k` and all
counts are reported alongside so you can apply your own judgment.

## 4. Reproducibility

- **Config-driven:** every knob lives in `config.yaml`; a run = (code version +
  config + cached source snapshots).
- **Response cache:** raw API responses are stored under `.http_cache/`; re-runs
  read identical bytes instead of re-querying mutable upstream data.
- **Deterministic transforms:** dedupe/classify/rank are pure functions with
  stable ordering; no randomness.
- **Pinned, minimal deps:** core logic is standard-library only; only `requests`
  and `PyYAML` are required at runtime.
- **Tested:** unit tests for classify/dedupe/rank and an end-to-end offline test
  on bundled fixtures (`make test`).

## 5. Reproducing a real result

```bash
export CENSUS_API_KEY=...        # free, recommended
make run STATES=NY,NJ,CT,MA,RI,PA,AZ,OR,CA,IL,TX,FL
```

Coverage is your choice of states; for a true national answer, include all 50 +
DC (and consider self-hosting Overpass).

## 6. Sample (offline) demonstration

`make sample` runs on `data/sample/*.json` — a **synthetic** fixture, not a real
extract — and writes `data/processed/*_sample.*`. It produces a sensible result
(New Haven, CT on top — coal-fired *apizza* country) and exercises every code
path: a node+way duplicate that must collapse, classification via OSM tag /
strong keyword / ambiguous brick-oven / conventional / unknown, and the ranking
filters (Stamford has only one wood-fired pizzeria and is correctly dropped).

## 7. Assumptions, biases, and threats to validity

- **OSM completeness varies by region.** Dense, well-mapped metros are
  over-represented vs. rural areas; absolute counts are lower bounds. Per-capita
  comparisons assume *roughly uniform* mapping completeness across compared
  cities — not strictly true. Report coverage caveats with any ranking.
- **`addr:city` sparsity** drops some restaurants from the ranking (no city to
  join). Quantify this from `restaurants.csv` (records with empty `city_norm`).
- **Classifier precision/recall** depends on the keyword tables. Many genuine
  wood/coal ovens aren't described as such in OSM; without website enrichment
  they're missed (recall ceiling). Conversely, "brick oven" can be gas-fired
  (precision risk) — hence its sub-threshold confidence.
- **"City" definition.** Census places undercount metro phenomena: a famous
  pizzeria in a separately-incorporated suburb counts for the suburb, not the
  core city. Consider ranking at the **CBSA/metro** level too.
- **Population vintage.** ACS 5-year is a smoothed multi-year estimate; pick the
  dataset year in config and report it.
- **Per-capita vs. small numbers.** Even with floors and shrinkage, low counts
  are noisy; confidence intervals (e.g. a Poisson/Wilson interval on the rate)
  would strengthen claims.

## 8. How to harden it

- **Point-in-polygon city assignment** using Census **TIGER/Line place**
  shapefiles (with `shapely`) instead of `addr:city` — eliminates the address-
  tag dependency and is the single biggest accuracy upgrade.
- **Enable website enrichment** (`classify.use_website_text: true`) to lift
  recall, staying within robots.txt.
- **Cross-source corroboration** via **Wikidata** (SPARQL, CC0) — e.g. items
  with `instance of: pizzeria` and an oven/`fuel` qualifier — to validate OSM
  and de-duplicate across sources.
- **Hand-label a validation sample** to measure classifier precision/recall and
  tune the threshold/keywords.
- **Add interval estimates** on the per-capita rate for honest comparisons.

## 9. Licensing & attribution

- **Code:** MIT.
- **OpenStreetMap data:** © OpenStreetMap contributors, licensed **ODbL**.
  Any published result or derived dataset must credit "© OpenStreetMap
  contributors" and, if redistributed, comply with ODbL share-alike.
- **U.S. Census data:** U.S. Government public domain.
- **Website text** (if enrichment is enabled) remains the property of each site;
  we use only small excerpts for classification and store derived labels, not
  reproductions.
