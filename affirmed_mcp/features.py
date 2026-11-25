"""Deterministic claim feature extraction (spec §6B).

Each extraction rule has a stable identifier, a supported claim-type mapping,
positive/negative fixtures in tests, and explicit failure behavior. Feature
extraction is NOT general natural-language inference: unsupported reasoning
types route to ``FEATURE_UNVERIFIABLE`` rather than confident regex verdicts.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

FEATURE_EXTRACTOR_VERSION = "1"

# Stable rule identifiers (recorded in receipts)
RULE_AVAILABILITY_TOKEN = "RULE_AVAILABILITY_TOKEN_V1"
RULE_NUMERIC_TOKEN = "RULE_NUMERIC_TOKEN_V1"
RULE_NEGATION = "RULE_NEGATION_V1"
RULE_QUANTIFIER = "RULE_QUANTIFIER_V1"
RULE_DATE_TOKEN = "RULE_DATE_TOKEN_V1"
RULE_GEO_TOKEN = "RULE_GEO_TOKEN_V1"
RULE_FIELD_HINT = "RULE_FIELD_HINT_V1"
RULE_UNSUPPORTED_REASONING = "RULE_UNSUPPORTED_REASONING_V1"

AVAILABILITY_ALWAYS = {"24/7", "24-7", "24 hours", "24hours", "around the clock", "day or night", "any hour", "always available", "anytime", "any time"}
AVAILABILITY_LIMITED = {"business hours", "weekdays", "weekends", "holidays"}
QUANTIFIER_TOKENS = ("all", "only", "except", "excluding", "at least", "up to")
NEGATION_RE = re.compile(r"\b(?:not|no|never|doesn't|does not|don't|do not|isn't|is not|aren't|are not|won't|will not)\b", re.IGNORECASE)
CURRENCY_RE = re.compile(r"(?:US\$|\$|USD)\s*(\d[\d,]*(?:\.\d+)?)\s*(dollars?)?", re.IGNORECASE)
NUMBER_UNIT_RE = re.compile(r"\b(\d[\d,]*(?:\.\d+)?)\s*(miles?|mi|kilometers?|km|hours?|hrs|minutes?|mins|days?|years?|usd|dollars?|%|percent)\b", re.IGNORECASE)
BARE_NUMBER_RE = re.compile(r"\b(\d[\d,]*(?:\.\d+)?)\b")
ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
YEAR_RE = re.compile(r"\bsince\s+(\d{4})\b|\bin\s+(\d{4})\b", re.IGNORECASE)
GEO_RE = re.compile(r"\b(?:in|within|around|near|serving|throughout|across)\s+([A-Z][A-Za-z.]+(?:\s+[A-Z][A-Za-z.]+){0,2})")

UNIT_ALIASES = {
    "usd": "USD", "dollar": "USD", "dollars": "USD", "$": "USD",
    "mile": "mi", "miles": "mi", "mi": "mi",
    "kilometer": "km", "kilometers": "km", "km": "km",
    "hour": "h", "hours": "h", "hrs": "h",
    "minute": "min", "minutes": "min", "mins": "min",
    "day": "d", "days": "d", "year": "y", "years": "y",
    "percent": "%", "%": "%",
}

# Keyword -> candidate deterministic field names (explicit claim-type mapping).
FIELD_KEYWORDS: list[tuple[str, list[str]]] = [
    ("towing", ["towing_availability", "towing", "service_availability"]),
    ("tow", ["towing_availability", "towing", "service_availability"]),
    ("lockout", ["lockout_service", "services"]),
    ("jump", ["jump_start", "battery_service", "services"]),
    ("battery", ["battery_service", "services"]),
    ("fuel", ["fuel_delivery", "services"]),
    ("tire", ["tire_change", "flat_tire", "services"]),
    ("flat", ["tire_change", "flat_tire", "services"]),
    ("winch", ["winch_out", "services"]),
    ("price", ["price", "fee", "cost", "pricing"]),
    ("cost", ["price", "fee", "cost", "pricing"]),
    ("fee", ["price", "fee", "cost", "pricing"]),
    ("charge", ["price", "fee", "cost", "pricing"]),
    ("available", ["availability", "business_hours", "service_availability"]),
    ("availability", ["availability", "business_hours", "service_availability"]),
    ("hour", ["availability", "business_hours", "service_availability"]),
    ("service area", ["service_area", "coverage", "geo_scope"]),
    ("coverage", ["service_area", "coverage", "geo_scope"]),
    ("licensed", ["licensing", "license_status"]),
    ("insured", ["insurance", "insurance_status"]),
]

UNSUPPORTED_REASONING_MARKERS = (
    "why ", "because ", "reason ", "cause ", "should ", "better than", "best ",
    "recommend", "opinion", "believe", "think ", "feel ", "probably", "might ",
    "could ", "would ", "should ", "worth ", "better", "worse", "quality",
    "reliable", "trustworthy", "better choice",
)


@dataclass
class ExtractedNumber:
    value: float
    unit: str | None
    rule: str = RULE_NUMERIC_TOKEN


@dataclass
class ClaimFeatures:
    claim_type: str
    rules: list[str] = field(default_factory=list)
    numbers: list[ExtractedNumber] = field(default_factory=list)
    availability: str | None = None  # "always" | "limited" | None
    availability_phrase: str | None = None
    negated: bool = False
    negation_span: str | None = None
    quantifier: str | None = None
    quantifier_phrase: str | None = None
    dates: list[str] = field(default_factory=list)
    geos: list[str] = field(default_factory=list)
    candidate_fields: list[str] = field(default_factory=list)
    unsupported_reasoning: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_type": self.claim_type,
            "rules": self.rules,
            "numbers": [{"value": n.value, "unit": n.unit, "rule": n.rule} for n in self.numbers],
            "availability": self.availability,
            "availability_phrase": self.availability_phrase,
            "negated": self.negated,
            "negation_span": self.negation_span,
            "quantifier": self.quantifier,
            "quantifier_phrase": self.quantifier_phrase,
            "dates": self.dates,
            "geos": self.geos,
            "candidate_fields": self.candidate_fields,
            "unsupported_reasoning": self.unsupported_reasoning,
        }


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _norm_unit(unit: str | None) -> str | None:
    if unit is None:
        return None
    return UNIT_ALIASES.get(unit.lower(), unit)


def extract_features(claim_text: str, caller_field_hint: str | None = None) -> ClaimFeatures:
    """Deterministically extract supported feature types from an atomic claim."""
    text = _normalize(claim_text)
    lower = text.lower()
    rules: list[str] = []

    negated = False
    negation_span = None
    m = NEGATION_RE.search(text)
    if m:
        negated = True
        negation_span = m.group(0)
        rules.append(RULE_NEGATION)

    availability = None
    availability_phrase = None
    for phrase in AVAILABILITY_ALWAYS:
        if phrase in lower:
            availability = "always"
            availability_phrase = phrase
            rules.append(RULE_AVAILABILITY_TOKEN)
            break
    if availability is None:
        for phrase in AVAILABILITY_LIMITED:
            if phrase in lower:
                availability = "limited"
                availability_phrase = phrase
                rules.append(RULE_AVAILABILITY_TOKEN)
                break

    quantifier = None
    quantifier_phrase = None
    for q in QUANTIFIER_TOKENS:
        if re.search(rf"\b{re.escape(q)}\b", lower):
            quantifier = q
            quantifier_phrase = q
            rules.append(RULE_QUANTIFIER)
            break

    dates = ISO_DATE_RE.findall(text)
    for match in YEAR_RE.finditer(text):
        dates.append(next(g for g in match.groups() if g))
    if dates:
        rules.append(RULE_DATE_TOKEN)

    geos = [g.strip() for g in GEO_RE.findall(text)]
    if geos:
        rules.append(RULE_GEO_TOKEN)

    # Suppress bare-number tokens that are part of a recognised availability
    # shorthand (e.g. the "24" and "7" inside "24/7") so they are not
    # double-counted as independent numeric assertions.
    _AVAILABILITY_SHORTHAND_RES = [
        re.compile(r"\b24\s*/\s*7\b"),
        re.compile(r"\b24\s*[-\u2013]\s*7\b"),
        re.compile(r"\b24\s+hours?\b", re.IGNORECASE),
        re.compile(r"\b24\s+hrs?\b", re.IGNORECASE),
    ]

    numbers: list[ExtractedNumber] = []
    seen_spans: list[tuple[int, int]] = []
    for match in CURRENCY_RE.finditer(text):
        numbers.append(ExtractedNumber(float(match.group(1).replace(",", "")), "USD"))
        seen_spans.append(match.span())
    for match in NUMBER_UNIT_RE.finditer(text):
        if any(match.span() == s for s in seen_spans):
            continue
        unit = _norm_unit(match.group(2))
        numbers.append(ExtractedNumber(float(match.group(1).replace(",", "")), unit))
        seen_spans.append(match.span())
    if not numbers:
        # Determine spans consumed by availability shorthand before scanning
        # for bare numbers so we don't treat "24/7" as numeric claims 24 and 7.
        availability_spans: list[tuple[int, int]] = []
        for _rx in _AVAILABILITY_SHORTHAND_RES:
            availability_spans.extend(m.span() for m in _rx.finditer(text))
        bare = [
            m
            for m in BARE_NUMBER_RE.finditer(text)
            if not any(s <= m.start() and m.end() <= e for s, e in availability_spans)
        ]
        if bare and (quantifier in ("at least", "up to") or availability or "hour" in lower):
            for m in bare:
                numbers.append(ExtractedNumber(float(m.group(1).replace(",", "")), None))
    if numbers:
        rules.append(RULE_NUMERIC_TOKEN)

    candidate_fields: list[str] = []
    if caller_field_hint:
        candidate_fields.append(caller_field_hint)
        rules.append(RULE_FIELD_HINT)
    for keyword, fields in FIELD_KEYWORDS:
        if keyword in lower:
            for f in fields:
                if f not in candidate_fields:
                    candidate_fields.append(f)
    # Compound candidate fields: when a service keyword AND a price/cost
    # keyword are both present, generate combined field names like
    # "towing_price" so the verifier can match compound evidence fields.
    _SERVICE_KEYWORDS = {"towing", "tow", "lockout", "jump", "battery", "fuel", "tire", "flat", "winch"}
    _PRICE_KEYWORDS = {"price", "cost", "fee", "charge"}
    found_services = [k for k in _SERVICE_KEYWORDS if k in lower]
    found_prices = [k for k in _PRICE_KEYWORDS if k in lower]
    if found_services and found_prices:
        for svc in found_services:
            # Generate all common price/cost compound forms.
            for compound_suffix in ("price", "cost", "fee"):
                compound = f"{svc}_{compound_suffix}" if svc != "tow" else f"towing_{compound_suffix}"
                if compound not in candidate_fields:
                    candidate_fields.append(compound)

    unsupported_reasoning = any(marker in lower for marker in UNSUPPORTED_REASONING_MARKERS)
    if unsupported_reasoning:
        rules.append(RULE_UNSUPPORTED_REASONING)

    claim_type = _classify(negated, availability, numbers, quantifier, dates, geos, unsupported_reasoning)
    return ClaimFeatures(
        claim_type=claim_type,
        rules=rules,
        numbers=numbers,
        availability=availability,
        availability_phrase=availability_phrase,
        negated=negated,
        negation_span=negation_span,
        quantifier=quantifier,
        quantifier_phrase=quantifier_phrase,
        dates=dates,
        geos=geos,
        candidate_fields=candidate_fields,
        unsupported_reasoning=unsupported_reasoning,
    )


def _classify(negated, availability, numbers, quantifier, dates, geos, unsupported_reasoning) -> str:
    if unsupported_reasoning:
        return "unsupported_reasoning"
    if negated and (availability or numbers or True):
        return "negated_service"
    if availability:
        return "availability"
    if quantifier and numbers:
        return "quantified_numeric"
    if quantifier:
        return "quantified_service"
    if numbers:
        return "numeric_assertion"
    if dates:
        return "date_assertion"
    if geos:
        return "geo_scoped_service"
    return "unmapped"
