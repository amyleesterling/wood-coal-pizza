"""Classify a pizzeria's oven type from text and structured tags.

We classify into one of:

    "coal"          - coal-fired (a small, distinctive category in the US)
    "wood"          - wood-fired / wood-burning / brick + wood signals
    "wood_or_coal"  - clearly solid-fuel but fuel not disambiguated
    "gas_electric"  - explicitly conventional (excluded from the headline count)
    "unknown"       - no signal either way

Signals, in priority order:
  1. OSM structured tags (`oven=wood|coal|electric|gas`, `fuel=*`) - highest
     trust because a mapper asserted it explicitly.
  2. Strong keyword phrases in the name / description / website text.
  3. Weaker, ambiguous phrases ("brick oven", "Neapolitan") that *suggest*
     wood but are not conclusive.

The function returns a label, a confidence in [0, 1], and the evidence used,
so every classification in the output is auditable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .utils import normalize_text

# ---------------------------------------------------------------------------
# Keyword tables. Each maps a normalized phrase -> weight contributed to a
# fuel category. Weights are additive; the dominant category wins and
# confidence is squashed to [0, 1].
# ---------------------------------------------------------------------------

# Phrases that essentially guarantee the category.
STRONG_COAL = {
    "coal fired": 1.0, "coal oven": 1.0, "coal burning": 1.0,
    "coal brick oven": 1.0, "anthracite": 1.0, "coal fired pizza": 1.0,
}
STRONG_WOOD = {
    "wood fired": 1.0, "wood oven": 1.0, "wood burning": 1.0,
    "wood roasted": 0.8, "forno a legna": 1.0, "legna": 0.7,
    "wood fire": 0.9, "wood-fired": 1.0, "log fired": 0.9,
}

# Phrases that indicate solid-fuel but don't pin the fuel down.
AMBIGUOUS_SOLID_FUEL = {
    "brick oven": 0.45, "brick fired": 0.5, "stone oven": 0.35,
    "hearth": 0.35, "open flame": 0.3, "forno": 0.4,
}

# Phrases that suggest (but don't prove) wood specifically.
WOOD_LEANING = {
    "neapolitan": 0.45, "napoletana": 0.45, "vera pizza": 0.4,
    "vpn certified": 0.6, "900 degrees": 0.5, "00 flour": 0.2,
    "artisan pizza": 0.15,
}

# Phrases that indicate a conventional oven (negative signal).
CONVENTIONAL = {
    "gas fired": 1.0, "gas oven": 0.9, "electric oven": 1.0,
    "deck oven": 0.5, "conveyor oven": 0.9,
}

# OSM tag values -> (label, confidence). These dominate when present.
OSM_OVEN_TAG = {
    "wood": ("wood", 0.97),
    "wood_fired": ("wood", 0.97),
    "coal": ("coal", 0.97),
    "charcoal": ("coal", 0.85),
    "gas": ("gas_electric", 0.95),
    "electric": ("gas_electric", 0.95),
}

POSITIVE_LABELS = {"wood", "coal", "wood_or_coal"}


@dataclass
class Classification:
    label: str
    confidence: float
    evidence: List[str] = field(default_factory=list)

    @property
    def is_wood_or_coal(self) -> bool:
        return self.label in POSITIVE_LABELS

    def as_dict(self) -> Dict[str, object]:
        return {
            "oven_label": self.label,
            "oven_confidence": round(self.confidence, 3),
            "oven_evidence": "; ".join(self.evidence),
        }


def _scan(text: str, table: Dict[str, float], evidence: List[str],
          prefix: str) -> float:
    score = 0.0
    for phrase, weight in table.items():
        if phrase in text:
            score += weight
            evidence.append(f"{prefix}:'{phrase}'")
    return score


def classify(
    name: Optional[str] = None,
    description: Optional[str] = None,
    osm_tags: Optional[Dict[str, str]] = None,
    website_text: Optional[str] = None,
) -> Classification:
    """Classify oven type from available signals.

    All text inputs are optional; pass whatever is available. ``osm_tags`` is
    the raw OSM tag dict (e.g. {"oven": "wood", "cuisine": "pizza"}).
    """
    osm_tags = osm_tags or {}
    evidence: List[str] = []

    # 1) Trust an explicit OSM oven/fuel tag above everything else.
    for tag_key in ("oven", "fuel", "oven:fuel"):
        tag_val = normalize_text(osm_tags.get(tag_key))
        if tag_val in OSM_OVEN_TAG:
            label, conf = OSM_OVEN_TAG[tag_val]
            return Classification(label, conf, [f"osm:{tag_key}={tag_val}"])

    # 2) Build a combined text blob from the remaining signals.
    blob = " ".join(
        normalize_text(t)
        for t in (
            name,
            description,
            osm_tags.get("description"),
            osm_tags.get("cuisine"),
            website_text,
        )
        if t
    )
    if not blob:
        return Classification("unknown", 0.0, [])

    coal = _scan(blob, STRONG_COAL, evidence, "coal")
    wood = _scan(blob, STRONG_WOOD, evidence, "wood")
    solid = _scan(blob, AMBIGUOUS_SOLID_FUEL, evidence, "solid")
    wood_lean = _scan(blob, WOOD_LEANING, evidence, "woodlean")
    conv = _scan(blob, CONVENTIONAL, evidence, "conv")

    # A strong conventional signal with no solid-fuel signal => conventional.
    if conv >= 0.9 and (coal + wood + solid) == 0:
        return Classification("gas_electric", min(conv, 1.0), evidence)

    # Decide among solid-fuel categories.
    coal_total = coal
    wood_total = wood + wood_lean
    # Ambiguous solid-fuel evidence supports "wood_or_coal" but, in the US,
    # leans wood; we split it: it boosts both, slightly more to wood.
    if coal_total == 0 and wood_total == 0 and solid == 0:
        return Classification("unknown", 0.0, evidence)

    # Net out a conventional counter-signal.
    penalty = min(conv * 0.5, 0.4)

    if coal_total > 0 and wood_total > 0:
        # Both named (e.g. "wood & coal fired"): report the dominant one but
        # keep it honest as wood_or_coal if they're close.
        if abs(coal_total - wood_total) < 0.5:
            label, raw = "wood_or_coal", max(coal_total, wood_total) + 0.3 * solid
        elif coal_total > wood_total:
            label, raw = "coal", coal_total + 0.2 * solid
        else:
            label, raw = "wood", wood_total + 0.2 * solid
    elif coal_total > 0:
        label, raw = "coal", coal_total + 0.2 * solid
    elif wood_total > 0:
        label, raw = "wood", wood_total + 0.3 * solid
    else:
        # Only ambiguous solid-fuel evidence (brick/stone/hearth).
        label, raw = "wood_or_coal", solid

    confidence = max(0.0, min(raw - penalty, 1.0))
    # Floor: ambiguous-only evidence shouldn't masquerade as high confidence.
    if label == "wood_or_coal" and coal_total == 0 and wood_total == 0:
        confidence = min(confidence, 0.6)

    return Classification(label, confidence, evidence)
