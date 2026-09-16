"""
street_name_cleaner.py

Standardizes US address formats for Vermont E911 data.

This module is self-contained: it has no runtime network or file
dependencies. Its reference tables (street-type abbreviations, directionals,
route classifications, etc.) were derived offline from a one-time survey of
four VCGI/E911 ArcGIS REST FeatureServer endpoints (road centerlines,
driveways, site/structure address points, hydrants) and a USPS ZIP+4
reference CSV for Vermont, so the full breadth of real-world address
variations in use statewide is baked into the lookup tables below rather
than fetched each run.

Intended to be imported as a library (e.g. from an FME Workspace Python
Caller / Custom Transformer) to clean full, primary, and secondary address
columns via `standardize_address()`.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Business-rule lookup tables
# ---------------------------------------------------------------------------

# Street-type abbreviation -> full name. Built from USPS Publication 28
# (Appendix C) plus every StreetSuffixAbbreviation observed in the VT USPS
# ZIP+4 reference data, cross-checked against the St_PosTyp domain used by
# the VCGI road centerline / address point / hydrant layers.
ROAD_TYPE_MAP: Dict[str, str] = {
    "ALY": "ALLEY", "ANX": "ANNEX", "AVE": "AVENUE", "BCH": "BEACH",
    "BLF": "BLUFF", "BLVD": "BOULEVARD", "BND": "BEND", "BR": "BRANCH",
    "BRG": "BRIDGE", "BRK": "BROOK", "CIR": "CIRCLE", "CIRS": "CIRCLES",
    "CLF": "CLIFF", "CLFS": "CLIFFS", "CMN": "COMMON", "CMNS": "COMMONS",
    "COR": "CORNER", "CRK": "CREEK", "CRST": "CREST", "CSWY": "CAUSEWAY",
    "CT": "COURT", "CTR": "CENTER", "CURV": "CURVE", "CV": "COVE",
    "DR": "DRIVE", "EST": "ESTATE", "ESTS": "ESTATES", "EXT": "EXTENSION",
    "FLDS": "FIELDS", "FLT": "FLAT", "FLTS": "FLATS", "FRST": "FOREST",
    "GDNS": "GARDENS", "GLN": "GLEN", "GRN": "GREEN", "GRNS": "GREENS",
    "GRV": "GROVE", "HBR": "HARBOR", "HL": "HILL", "HOLW": "HOLLOW",
    "HTS": "HEIGHTS", "HVN": "HAVEN", "HWY": "HIGHWAY", "IS": "ISLAND",
    "KNL": "KNOLL", "KNLS": "KNOLLS", "LDG": "LODGE", "LF": "LOAF",
    "LGTS": "LIGHTS", "LK": "LAKE", "LN": "LANE", "LNDG": "LANDING",
    "LOOP": "LOOP", "MALL": "MALL", "MDW": "MEADOW", "MDWS": "MEADOWS",
    "MEWS": "MEWS", "MNR": "MANOR", "MT": "MOUNT", "MTN": "MOUNTAIN",
    "ORCH": "ORCHARD", "PARK": "PARK", "PASS": "PASS", "PATH": "PATH",
    "PIKE": "PIKE", "PKWY": "PARKWAY", "PL": "PLACE", "PLN": "PLAIN",
    "PLNS": "PLAINS", "PLZ": "PLAZA", "PNE": "PINE", "PNES": "PINES",
    "PT": "POINT", "RD": "ROAD", "RDG": "RIDGE", "ROW": "ROW",
    "RTE": "ROUTE", "RUN": "RUN", "SHR": "SHORE", "SHRS": "SHORES",
    "SPGS": "SPRINGS", "SPUR": "SPUR", "SQ": "SQUARE", "ST": "STREET",
    "STA": "STATION", "TER": "TERRACE", "TPKE": "TURNPIKE", "TRAK": "TRACK",
    "TRCE": "TRACE", "TRL": "TRAIL", "VIS": "VISTA", "VLG": "VILLAGE",
    "VLY": "VALLEY", "VW": "VIEW", "VWS": "VIEWS", "WALK": "WALK",
    "WAY": "WAY", "XING": "CROSSING", "XRD": "CROSSROAD",
    "BYPASS": "BYPASS", "EXTENTION": "EXTENSION", "FALLS": "FALLS",
    "FIELD": "FIELD", "FORK": "FORK", "HILLS": "HILLS", "MILL": "MILL",
    "PEAK": "PEAK", "WALL": "WALL", "WOODS": "WOODS",
}
# Allow already-expanded full words to pass through unchanged (idempotency).
ROAD_TYPE_MAP.update({full: full for full in set(ROAD_TYPE_MAP.values())})

# Non-highway address prefixes. Highway-specific "Route"/"Rt"/"Rte"
# handling is done separately in `standardize_highways` per rule 6.
PREFIX_MAP: Dict[str, str] = {
    "RT": "ROUTE",
    "RTE": "ROUTE",
}

PO_BOX_RE = re.compile(r"^(?:P\s*O\s*B(?:OX)?|POB)\b\.?\s*(\d+)?", re.IGNORECASE)

INTERSTATE_RE = re.compile(r"^I[\s-]?(\d+[A-Z]?)\b")
ROUTE_RE = re.compile(r"^(?:US\s+|VT\s+)?(?:ROUTE|RTE|RT)\b\.?\s*(\d+[A-Z]?)\b")

# Vermont's actual US Routes. Alphanumeric variants of these numbers (2A,
# 4A, 5A, 7A, 7B, ...) are all VT Routes, never US Routes -- see
# `standardize_highways()`.
US_ROUTES = {2, 4, 5, 7, 302}

ORDINAL_MAP: Dict[int, str] = {
    1: "FIRST", 2: "SECOND", 3: "THIRD", 4: "FOURTH", 5: "FIFTH",
    6: "SIXTH", 7: "SEVENTH", 8: "EIGHTH", 9: "NINTH", 10: "TENTH",
    11: "ELEVENTH", 12: "TWELFTH", 13: "THIRTEENTH", 14: "FOURTEENTH",
    15: "FIFTEENTH", 16: "SIXTEENTH", 17: "SEVENTEENTH", 18: "EIGHTEENTH",
    19: "NINETEENTH", 20: "TWENTIETH",
}
ORDINAL_RE = re.compile(r"^(\d{1,2})(?:ST|ND|RD|TH)$")

# Only abbreviated forms trigger the "prefix directional" heuristic. An
# already-spelled-out word immediately after the address number (e.g.
# "South" in "88 South Hill Rd") is left alone as part of the street name
# itself rather than split out as a separate directional segment.
PREFIX_DIRECTIONAL_MAP: Dict[str, str] = {
    "N": "NORTH", "S": "SOUTH", "E": "EAST", "W": "WEST",
    "NE": "NORTHEAST", "NW": "NORTHWEST", "SE": "SOUTHEAST", "SW": "SOUTHWEST",
}

# Post-directionals are cardinal-only per USPS convention (confirmed against
# the VT reference data: StreetPostDirectional only ever contains N/S/E/W).
SUFFIX_DIRECTIONAL_ABBR: Dict[str, str] = {
    "N": "N", "S": "S", "E": "E", "W": "W",
    "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W",
}

# Same as INTERSTATE_RE / ROUTE_RE, but anchored to the *end* of the text
# (with an optional trailing suffix directional still allowed after the
# route/interstate number) instead of the start, and found anywhere via
# `.search()` rather than requiring the highway to lead the string. Used to
# detect a local alias road name given *before* the highway (e.g. "Weston Rd
# Route 155") -- see `_detect_reversed_highway_alias()`.
_TRAILING_DIRECTIONAL_ALT = "|".join(SUFFIX_DIRECTIONAL_ABBR)
TRAILING_INTERSTATE_RE = re.compile(
    r"I[\s-]?(\d+[A-Z]?)\b(?:\s+(" + _TRAILING_DIRECTIONAL_ALT + r"))?\s*$"
)
TRAILING_ROUTE_RE = re.compile(
    r"(?:US\s+|VT\s+)?(?:ROUTE|RTE|RT)\b\.?\s*(\d+[A-Z]?)\b(?:\s+(" + _TRAILING_DIRECTIONAL_ALT + r"))?\s*$"
)

SECONDARY_UNIT_MAP: Dict[str, str] = {
    "APT": "UNIT", "APARTMENT": "UNIT", "STE": "UNIT", "SUITE": "UNIT",
    "ROOM": "UNIT", "RM": "UNIT", "SPC": "UNIT", "SPACE": "UNIT", "UNIT": "UNIT",
}
SECONDARY_RE = re.compile(
    r"\b(" + "|".join(SECONDARY_UNIT_MAP) + r")\b\.?\s*#?\s*([A-Z0-9\-]+)?"
)
BARE_HASH_RE = re.compile(r"#\s*([A-Z0-9\-]+)")


# ---------------------------------------------------------------------------
# Base formatting helpers
# ---------------------------------------------------------------------------

def clean_whitespace(text: str) -> str:
    """Strip leading/trailing whitespace and collapse internal runs of
    whitespace down to a single space."""
    return re.sub(r"\s+", " ", text.strip())


def _fix_fraction_spacing(text: str) -> str:
    """Normalize spaced-out fractions so there is no space around the slash
    (e.g. "1 / 2" -> "1/2")."""
    return re.sub(r"(\d+)\s*/\s*(\d+)", r"\1/\2", text)


def _to_number(token: str) -> Optional[int]:
    match = re.match(r"^(\d+)", token)
    return int(match.group(1)) if match else None


# A true "full address" may carry a trailing ", <City>, <ST> [ZIP[-4]]"
# tail. This module only standardizes address numbers and street names, not
# city/state/zip, so that tail (if present) is dropped up front rather than
# fed into the street-name parsing below.
CITY_STATE_ZIP_TAIL_RE = re.compile(
    r",\s*[A-Z][A-Z .'\-]*,\s*[A-Z]{2}(?:\s+\d{5}(?:-\d{4})?)?\s*$"
)


def strip_city_state_zip(text: str) -> str:
    """Drop a trailing ", <City>, <ST> [ZIP[-4]]" tail from a full mailing
    address (e.g. "3 E MAIN ST N, SOUTH BURLINGTON, VT 05403" ->
    "3 E MAIN ST N"). A no-op if no such tail is present."""
    return CITY_STATE_ZIP_TAIL_RE.sub("", text).strip()


# ---------------------------------------------------------------------------
# Secondary (unit) address parsing
# ---------------------------------------------------------------------------

def extract_secondary_unit(text: str) -> tuple[str, Optional[str]]:
    """Split off a secondary/unit designation from the end of an address
    string. Returns (remaining_primary_text, secondary_address)."""
    match = None
    for candidate in SECONDARY_RE.finditer(text):
        match = candidate  # keep the last match (unit is expected at the end)

    if match:
        keyword = SECONDARY_UNIT_MAP[match.group(1)]
        value = (match.group(2) or "").strip("-")
        primary = (text[: match.start()] + " " + text[match.end():]).strip()
        primary = primary.rstrip(", ").strip()
        secondary = f"{keyword} {value}".strip() if value else keyword
        return clean_whitespace(primary), clean_whitespace(secondary)

    # Fall back to a bare "#4" style unit with no keyword.
    bare = BARE_HASH_RE.search(text)
    if bare:
        value = bare.group(1).strip("-")
        primary = (text[: bare.start()] + " " + text[bare.end():]).strip()
        primary = primary.rstrip(", ").strip()
        secondary = f"UNIT {value}" if value else None
        return clean_whitespace(primary), secondary

    return clean_whitespace(text.rstrip(", ")), None


# ---------------------------------------------------------------------------
# Address number parsing
# ---------------------------------------------------------------------------

# Rural VT camp/lot-style address-number prefixes seen in the VCGI address
# point data's AddNum_Pre field (e.g. "H 5 Stonehedge Dr"), in addition to a
# lone letter.
_ADDRESS_NUMBER_PREFIX_WORDS = ("CABIN", "LEANTO", "LOT", "TENT", "SLL", "SLR", "SUL", "SUR")
_ADDRESS_NUMBER_PREFIX_RE = re.compile(
    r"^(?:[A-Z]|" + "|".join(_ADDRESS_NUMBER_PREFIX_WORDS) + r")\s+(?=\d)"
)


def _merge_address_number_parts(prefix: str, base: Optional[str], suffix: str) -> Optional[str]:
    """Attach an address-number prefix (e.g. "H") and/or suffix (e.g. "A")
    onto an already-normalized numeric core (e.g. "5", "33 1/2", "1-5").
    A single letter merges directly onto the number with no space (rule 3,
    e.g. "H5", "28A"), but a multi-letter prefix/suffix word (e.g. camp/lot
    numbering like "LOT 5") and a half-value fraction keep their space."""
    if not base:
        return None
    result = base

    suffix = suffix.strip().upper().replace(".", "") if suffix else ""
    if suffix:
        result = f"{result}{suffix}" if re.match(r"^[A-Z]$", suffix) else f"{result} {suffix}"

    prefix = prefix.strip().upper().replace(".", "") if prefix else ""
    if prefix:
        result = f"{prefix}{result}" if re.match(r"^[A-Z]$", prefix) else f"{prefix} {result}"

    return result


def _is_lone_street_name_remainder(remainder: str) -> bool:
    """True if, after a candidate single-letter address-number suffix, all
    that's left is empty, a bare road type (e.g. "ST"), or a road type plus
    a trailing suffix directional (e.g. "ST N") -- with no separate street
    name in between. That's the signal that the letter itself is actually a
    stand-alone single-letter street name (e.g. "26 G St", where "G" is the
    whole street name, not a "26-G"-style address-number suffix), rather
    than a genuine alphanumeric suffix on the number (e.g. "28-A Main St",
    where "Main St" still follows)."""
    tokens = [t for t in remainder.strip().split(" ") if t]
    if tokens and tokens[-1].rstrip(",") in SUFFIX_DIRECTIONAL_ABBR:
        tokens = tokens[:-1]
    return not tokens or (len(tokens) == 1 and tokens[0].rstrip(",") in ROAD_TYPE_MAP)


def extract_address_number(text: str) -> tuple[Optional[str], str]:
    """Pull a leading house number off `text`, honoring half-value,
    alphanumeric, and camp/lot address-number-prefix (e.g. "H 5 Main St" ->
    "H5") formatting rules. Returns (address_number, remainder)."""
    prefix_match = _ADDRESS_NUMBER_PREFIX_RE.match(text)
    prefix = prefix_match.group(0).strip() if prefix_match else ""
    body = text[prefix_match.end():] if prefix_match else text

    # Half value, e.g. "33 1/2 Main St" -> "33 1/2"
    match = re.match(r"^(\d+)\s+(\d+/\d+)\b\s*", body)
    if match:
        number = _merge_address_number_parts(prefix, f"{match.group(1)} {match.group(2)}", "")
        return number, body[match.end():]

    # Double whole-number, e.g. "48 16 Outerbay Way" -> address number
    # "48 16" (some rural/lot-style addressing uses a two-part whole
    # number). Only treated as part of the number when a real name clearly
    # follows -- a bare second number followed by nothing but a road type
    # could instead be a legitimate numbered street name (e.g. "5 42 St"),
    # same disambiguation as the single-letter case below.
    match = re.match(r"^(\d+)\s+(\d+)\b\s*", body)
    if match and not _is_lone_street_name_remainder(body[match.end():]):
        number = _merge_address_number_parts(prefix, f"{match.group(1)} {match.group(2)}", "")
        return number, body[match.end():]

    # Alphanumeric, e.g. "28-A" / "28 A" -> "28A". A lone N/S/E/W is never
    # merged in here since that's a directional word, not a unit letter,
    # and neither is a letter that's actually a stand-alone single-letter
    # street name (e.g. "26 G St") -- see `_is_lone_street_name_remainder()`.
    match = re.match(r"^(\d+)[\s-]?([A-Za-z])\b\s*", body)
    if (
        match
        and match.group(2).upper() not in PREFIX_DIRECTIONAL_MAP
        and not _is_lone_street_name_remainder(body[match.end():])
    ):
        number = _merge_address_number_parts(prefix, match.group(1), match.group(2))
        return number, body[match.end():]

    # Plain number
    match = re.match(r"^(\d+)\b\s*", body)
    if match:
        number = _merge_address_number_parts(prefix, match.group(1), "")
        return number, body[match.end():]

    return None, text


# ---------------------------------------------------------------------------
# Ordinal expansion
# ---------------------------------------------------------------------------

def expand_ordinal_token(token: str) -> str:
    match = ORDINAL_RE.match(token)
    if match:
        num = int(match.group(1))
        if num in ORDINAL_MAP:
            return ORDINAL_MAP[num]
    return token


# ---------------------------------------------------------------------------
# Highway / route parsing
# ---------------------------------------------------------------------------

def standardize_highways(remainder: str) -> tuple[Optional[str], str]:
    """Detect an Interstate or numbered Route at the start of `remainder`.
    Returns (route_phrase_or_None, rest_of_remainder)."""
    match = INTERSTATE_RE.match(remainder)
    if match:
        return f"INTERSTATE {match.group(1)}", remainder[match.end():].strip()

    match = ROUTE_RE.match(remainder)
    if match:
        route_num = match.group(1)
        # Only a plain numeric route number (no alphanumeric suffix) can be
        # a US Route. VT's alphanumeric route variants (2A, 4A, 5A, 7A, 7B,
        # ...) are all state routes, never US Routes, even when their base
        # number matches one (e.g. "2A" is a VT Route, not US Route 2).
        is_us_route = route_num.isdigit() and _to_number(route_num) in US_ROUTES
        prefix = "US" if is_us_route else "VT"
        return f"{prefix} ROUTE {route_num}", remainder[match.end():].strip()

    return None, remainder


def _route_phrase_for(route_num: str, is_interstate: bool) -> str:
    if is_interstate:
        return f"INTERSTATE {route_num}"
    is_us_route = route_num.isdigit() and _to_number(route_num) in US_ROUTES
    return f"{'US' if is_us_route else 'VT'} ROUTE {route_num}"


def _process_highway_tail(route_phrase: str, tail: str) -> tuple[str, Optional[str], Optional[str]]:
    """Handle whatever text (if any) follows a leading Interstate/Route
    phrase. Returns (street_name, suffix_directional, alias):

    - Nothing left -> the route phrase alone.
    - Just a bare directional (e.g. "W" in "Route 22A W") -> the route's own
      suffix directional, same as before this existed.
    - A single leading directional followed by nothing but a road type (e.g.
      "N Ext" in "Route 7B N Ext") -> a route extension/modifier, not a
      separate road -- expanded and folded directly into the route's name
      (e.g. "ROUTE 7B N EXTENSION"), preserving the original word order
      rather than the fixed number/name/type/suffix assembly order used
      elsewhere, since "extension" grammatically follows its directional.
    - A single leading directional followed by a real name-plus-road-type
      (e.g. "W Tinmouth Rd" in "Route 133 W Tinmouth Rd") -> that's a
      distinct local alias road name, not part of the route -- the leading
      directional stays with the route as its own suffix directional, and
      the rest is parsed and returned separately as `alias`.
    - Anything else (e.g. "Central" in "Route 7B Central", with no road type
      of its own) -- isn't confused for an alias or an extension; it's kept
      as part of the route's own name, same as free text."""
    tokens = [t for t in tail.strip().split(" ") if t]
    if not tokens:
        return route_phrase, None, None

    if len(tokens) == 1 and tokens[0] in SUFFIX_DIRECTIONAL_ABBR:
        return route_phrase, SUFFIX_DIRECTIONAL_ABBR[tokens[0]], None

    mod_dir = None
    remaining = tokens
    if tokens[0] in SUFFIX_DIRECTIONAL_ABBR:
        mod_dir = SUFFIX_DIRECTIONAL_ABBR[tokens[0]]
        remaining = tokens[1:]

    if len(remaining) == 1 and remaining[0] in ROAD_TYPE_MAP:
        pieces = [route_phrase] + ([mod_dir] if mod_dir else []) + [ROAD_TYPE_MAP[remaining[0]]]
        return " ".join(pieces), None, None

    if len(remaining) >= 2 and remaining[-1] in ROAD_TYPE_MAP:
        alias_name, alias_road_type, _ = parse_street_remainder(" ".join(remaining))
        alias = " ".join(part for part in (alias_name, alias_road_type) if part)
        return route_phrase, mod_dir, alias

    pieces = [route_phrase] + ([mod_dir] if mod_dir else []) + remaining
    return " ".join(pieces), None, None


def _detect_reversed_highway_alias(text: str) -> Optional[tuple[str, Optional[str], Optional[str]]]:
    """Detect a local alias road name given *before* an Interstate/Route
    phrase that runs to the end of the text (e.g. "Weston Rd Route 155").
    Only matches if the leading text actually looks like a real "name plus
    road type" -- e.g. "Business" in "Business Route 4" or "Old" in "Old
    Route 110" don't qualify (no road type of their own), so those are left
    alone entirely rather than misread as an alias. Returns
    (street_name, suffix_directional, alias), or None if there's no
    qualifying alias here."""
    for regex, is_interstate in ((TRAILING_ROUTE_RE, False), (TRAILING_INTERSTATE_RE, True)):
        match = regex.search(text)
        if not match:
            continue
        lead = text[:match.start()].strip()
        lead_tokens = [t for t in lead.split(" ") if t]
        if len(lead_tokens) < 2 or lead_tokens[-1] not in ROAD_TYPE_MAP:
            continue
        route_phrase = _route_phrase_for(match.group(1), is_interstate)
        suffix_directional = SUFFIX_DIRECTIONAL_ABBR.get(match.group(2)) if match.group(2) else None
        alias_name, alias_road_type, _ = parse_street_remainder(lead)
        alias = " ".join(part for part in (alias_name, alias_road_type) if part)
        return route_phrase, suffix_directional, alias
    return None


def parse_highway(text: str) -> Optional[tuple[str, Optional[str], Optional[str]]]:
    """Detect an Interstate/Route anywhere in `text` -- leading it as usual,
    or with a local alias road name attached before or after it -- and
    return (street_name, suffix_directional, alias). Returns None if `text`
    isn't a highway at all, in which case the caller should fall through to
    ordinary street-name parsing."""
    route_phrase, tail = standardize_highways(text)
    if route_phrase:
        return _process_highway_tail(route_phrase, tail)
    return _detect_reversed_highway_alias(text)


# ---------------------------------------------------------------------------
# Directional parsing
# ---------------------------------------------------------------------------

def parse_prefix_directional(remainder: str, only_if_more_follows: bool = False) -> tuple[Optional[str], str]:
    """Extract a leading single-letter prefix directional (e.g. "E" in
    "E Main St"). When `only_if_more_follows` is True, the letter is only
    treated as a prefix directional if something more than a bare road type
    remains after it; otherwise (e.g. "E St", with nothing else left) it's
    assumed to be a stand-alone single-letter street name (e.g. "E Street")
    and left alone -- same disambiguation as `_is_lone_street_name_remainder()`.
    When False (the normal free-text case), a leading abbreviation is
    always treated as a prefix directional, as before."""
    tokens = remainder.split(" ", 1)
    first = tokens[0] if tokens else ""
    if first in PREFIX_DIRECTIONAL_MAP:
        rest = (tokens[1] if len(tokens) > 1 else "").strip()
        if only_if_more_follows and _is_lone_street_name_remainder(rest):
            return None, remainder
        return PREFIX_DIRECTIONAL_MAP[first], rest
    return None, remainder


def parse_suffix_directional(
    tokens: List[str],
    known_suffix_directional: Optional[str] = None,
    only_abbreviated: bool = False,
) -> tuple[Optional[str], List[str]]:
    """Extract a trailing cardinal suffix directional from a street-name
    token list. Requires at least one other token so a lone street name that
    happens to equal a directional word (unusual, but possible) isn't
    stripped down to nothing.

    Some spelled-out directional words (e.g. "West", "South") are just as
    commonly the last word of the street's actual name (e.g. "Old West")
    as they are a genuine suffix directional. When `only_abbreviated` is
    True, a trailing *word* is only stripped out if it matches
    `known_suffix_directional` (i.e. a caller already has the true suffix
    directional from its own separate field, so this is confirmed
    redundant); a trailing single-letter *abbreviation* (N/S/E/W) is always
    treated as unambiguous and stripped regardless, matching how a prefix
    directional is only ever recognized from its abbreviated form. When
    `only_abbreviated` is False (the normal free-text case), any trailing
    token found in `SUFFIX_DIRECTIONAL_ABBR` is stripped, as before."""
    if not tokens or len(tokens) <= 1:
        return None, tokens
    last = tokens[-1]
    candidate = SUFFIX_DIRECTIONAL_ABBR.get(last)
    if not candidate:
        return None, tokens
    if only_abbreviated and last not in ("N", "S", "E", "W") and candidate != known_suffix_directional:
        return None, tokens
    return candidate, tokens[:-1]


def parse_street_remainder(
    remainder: str,
    known_road_type: Optional[str] = None,
    known_suffix_directional: Optional[str] = None,
    only_abbreviated_suffix: bool = False,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Parse whatever's left of a primary address after the address number
    and prefix directional (if any) have already been pulled off (or, when
    called directly on a bare street-name string that may still carry its
    own suffix/directional, the whole thing): extracts a trailing road type
    and/or suffix directional, expands ordinals, and disambiguates a leading
    "ST" as "SAINT". Returns (street_name, road_type, suffix_directional).

    Some words that are valid road types (e.g. "Hill", "Lake", "Mill") are
    just as commonly part of a street's actual name (e.g. "Canaan Hill Rd",
    where the real road type is "Rd" and "Hill" belongs in the name). When
    `known_road_type` is given -- i.e. a caller already has the true road
    type from its own separate field -- a trailing token is only stripped
    out as a (redundant, duplicate) road type if it actually matches
    `known_road_type`; otherwise it's assumed to be part of the name and
    left alone. When `known_road_type` is None (the normal free-text case,
    where there's nothing else to cross-check against), any trailing token
    found in `ROAD_TYPE_MAP` is stripped, as before.

    `known_suffix_directional` and `only_abbreviated_suffix` are the same
    idea applied to a trailing directional *word* (e.g. "West" in "Old
    West") -- see `parse_suffix_directional()`."""
    remainder = clean_whitespace((remainder or "").upper().replace(".", ""))
    tokens = [t for t in remainder.split(" ") if t]
    tokens = [expand_ordinal_token(t) for t in tokens]

    suffix_directional, tokens = parse_suffix_directional(
        tokens, known_suffix_directional, only_abbreviated_suffix
    )

    road_type = None
    if tokens:
        candidate = ROAD_TYPE_MAP.get(tokens[-1])
        if candidate and (known_road_type is None or candidate == known_road_type):
            road_type = candidate
            tokens = tokens[:-1]

    if tokens and tokens[0] == "ST":
        tokens[0] = "SAINT"

    # Any directional word left inside the street name itself (i.e. not the
    # recognized prefix/suffix position) must be spelled out in full, never
    # abbreviated (rule 5) -- but only when there's more than just this one
    # token. A single remaining token could itself be a legitimate
    # stand-alone single-letter street name (e.g. "E" in "E Street") rather
    # than an abbreviation embedded within a longer name.
    if len(tokens) > 1:
        tokens = [PREFIX_DIRECTIONAL_MAP.get(t, t) for t in tokens]

    street_name = " ".join(tokens) if tokens else None
    return street_name, road_type, suffix_directional


# ---------------------------------------------------------------------------
# PO Box parsing
# ---------------------------------------------------------------------------

def parse_po_box(text: str) -> Optional[Dict[str, Optional[str]]]:
    match = PO_BOX_RE.match(text)
    if not match:
        return None
    box_number = match.group(1)
    return {
        "address_number": box_number,
        "street_name": "PO BOX",
        "road_type": None,
        "prefix_directional": None,
        "suffix_directional": None,
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def standardize_address(raw_address: str) -> Dict[str, Any]:
    """Parse and standardize a raw US address string per Vermont E911
    business rules, returning the schema described in the module docstring."""
    if raw_address is None:
        raw_address = ""

    text = raw_address.upper().replace(".", "")
    text = _fix_fraction_spacing(text)
    text = clean_whitespace(text)
    text = strip_city_state_zip(text)

    primary_text, secondary_address = extract_secondary_unit(text)

    address_number: Optional[str] = None
    prefix_directional: Optional[str] = None
    street_name: Optional[str] = None
    road_type: Optional[str] = None
    suffix_directional: Optional[str] = None
    alias: Optional[str] = None

    po_box = parse_po_box(primary_text)
    highway_result = parse_highway(primary_text)

    if po_box:
        address_number = po_box["address_number"]
        street_name = po_box["street_name"]

    elif highway_result:
        street_name, suffix_directional, alias = highway_result

    else:
        address_number, remainder = extract_address_number(primary_text)
        remainder = remainder.strip()

        if address_number:
            prefix_directional, remainder = parse_prefix_directional(remainder, only_if_more_follows=True)

        highway_result = parse_highway(remainder)
        if highway_result:
            street_name, suffix_directional, alias = highway_result
        else:
            street_name, road_type, suffix_directional = parse_street_remainder(remainder)

    # --- assemble primary address -----------------------------------------
    if po_box:
        primary_parts = ["PO BOX"]
        if address_number:
            primary_parts.append(address_number)
    else:
        primary_parts = [
            part
            for part in [address_number, prefix_directional, street_name, road_type, suffix_directional]
            if part
        ]
    primary_address = " ".join(primary_parts) if primary_parts else ""

    full_address = primary_address
    if secondary_address:
        full_address = f"{primary_address}, {secondary_address}" if primary_address else secondary_address

    result = {
        "full_address": full_address or None,
        "parsed_segments": {
            "primary_address": primary_address or None,
            "address_number": address_number,
            "prefix_directional": prefix_directional,
            "street_name": street_name,
            "road_type": road_type,
            "suffix_directional": suffix_directional,
            "secondary_address": secondary_address,
            "alias": alias,
        },
    }
    return result


# ---------------------------------------------------------------------------
# Single-field normalization helpers
# ---------------------------------------------------------------------------
#
# `standardize_address()` above works on one combined address string, using
# position (leading number, trailing suffix, ...) to figure out what each
# token is. The helpers below instead normalize a value that a caller has
# already told us the role of -- e.g. "this attribute is the prefix
# directional" -- so no position-guessing is needed. They back the FME
# integration's granular per-field inputs, further down.

# Directional lookup that additionally accepts an already-spelled-out prefix
# directional (e.g. a source system that stores "East" rather than "E"),
# unlike `PREFIX_DIRECTIONAL_MAP`, which is abbreviation-only so that it
# doesn't misfire on an ordinary street name inside combined text.
_PREFIX_DIRECTIONAL_LOOKUP: Dict[str, str] = dict(PREFIX_DIRECTIONAL_MAP)
_PREFIX_DIRECTIONAL_LOOKUP.update({full: full for full in set(PREFIX_DIRECTIONAL_MAP.values())})


def normalize_prefix_directional(value: str) -> Optional[str]:
    """Normalize a value already known to be a prefix directional (e.g. "E"
    or "East") to its full spelled-out form."""
    token = value.strip().upper().replace(".", "") if value else ""
    return _PREFIX_DIRECTIONAL_LOOKUP.get(token, token) or None


def normalize_suffix_directional(value: str) -> Optional[str]:
    """Normalize a value already known to be a suffix directional (e.g. "N"
    or "North") to its cardinal abbreviation."""
    token = value.strip().upper().replace(".", "") if value else ""
    return SUFFIX_DIRECTIONAL_ABBR.get(token, token) or None


def normalize_road_type(value: str) -> Optional[str]:
    """Normalize a value already known to be a street-suffix/road type (e.g.
    "St" or "Street") to its full spelled-out form."""
    token = value.strip().upper().replace(".", "") if value else ""
    return ROAD_TYPE_MAP.get(token, token) or None


def normalize_street_name(value: str) -> Optional[str]:
    """Normalize a value already known to be the bare street name alone --
    with no directional or road type of its own -- e.g. a dedicated
    `St_Name`-style field that's already been split from the rest of the
    address. Expands ordinals and disambiguates a leading "St" as "Saint",
    but applies no directional/road-type stripping, since the caller has
    already guaranteed there isn't one to strip out."""
    text = clean_whitespace((value or "").upper().replace(".", ""))
    if not text:
        return None
    tokens = [expand_ordinal_token(t) for t in text.split(" ") if t]
    if tokens and tokens[0] == "ST":
        tokens[0] = "SAINT"
    return " ".join(tokens) if tokens else None


def normalize_address_number_token(value: str) -> Optional[str]:
    """Apply the half-value / alphanumeric formatting rules (rule 3) to a
    single, already-isolated address-number value (no surrounding street
    text), e.g. for a source system that stores the house number in its own
    column."""
    if not value:
        return None
    token = clean_whitespace(_fix_fraction_spacing(str(value).strip().upper().replace(".", "")))
    if not token:
        return None

    match = re.match(r"^(\d+)\s+(\d+/\d+)$", token)
    if match:
        return f"{match.group(1)} {match.group(2)}"

    match = re.match(r"^(\d+)[\s-]?([A-Za-z])$", token)
    if match and match.group(2).upper() not in PREFIX_DIRECTIONAL_MAP:
        return f"{match.group(1)}{match.group(2).upper()}"

    return token


def combine_number_range(low: str, high: str) -> Optional[str]:
    """Normalize a low/high number range preserved in separate columns (e.g.
    road-centerline address ranges, or a secondary-unit number range) into
    one token, such as "1-5". Each side is independently run through
    `normalize_address_number_token()` first. If only one side is present,
    or both sides are equal, returns that single normalized value rather
    than a range."""
    low_n = normalize_address_number_token(low)
    high_n = normalize_address_number_token(high)
    if low_n and high_n and low_n != high_n:
        return f"{low_n}-{high_n}"
    return low_n or high_n


def parse_primary_remainder(
    text: str,
    known_road_type: Optional[str] = None,
    known_suffix_directional: Optional[str] = None,
) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Parse a blended `PrimaryName`-style string -- the part of a primary
    address that comes after the address number, which may itself still
    carry a leading prefix directional (e.g. "E Main St") and/or a
    highway/route phrase, or an ordinary street name with a trailing road
    type / suffix directional. `known_road_type`, if given, is forwarded to
    `parse_street_remainder()` so an ambiguous trailing word (e.g. "Hill",
    "Lake") is only stripped out as a road type when it's redundant with
    that known value, rather than assumed to be one on its own.

    Likewise, a trailing directional *word* (e.g. "West" in "Old West") is
    only stripped out as a suffix directional when it matches
    `known_suffix_directional` -- i.e. a caller already has the true suffix
    directional from its own separate field, so this is confirmed redundant
    -- otherwise it's assumed to be part of the name, same as any other
    word. A trailing single-letter abbreviation (N/S/E/W) is still always
    treated as unambiguous.

    A *leading* single-letter abbreviation is handled the same way: it's
    only treated as a prefix directional if something more than a bare road
    type remains after it (`parse_prefix_directional(..., only_if_more_follows=True)`);
    otherwise (e.g. "E St", with nothing else left) it's a stand-alone
    single-letter street name and stays as-is. Unlike the trailing-word
    case above, this one has no pinned free-text test requiring the old
    "always strip" behavior, so `standardize_address()`'s own primary-
    address parsing applies the same disambiguation too (e.g. "5 E St"
    standardizes to "5 E STREET", not "5 EAST STREET").

    The trailing-suffix-directional-word disambiguation, by contrast, only
    applies to `PrimaryName`-style input (a caller that has its own
    dedicated suffix-directional field to fall back on); free-text parsing
    via `standardize_address()` keeps stripping any recognized trailing
    directional word, per its own pinned test case ("1st st south, apt #4").

    A highway (Interstate/Route) is detected via `parse_highway()`, which
    also picks up a local alias road name attached before or after it (e.g.
    "Weston Rd" in "Weston Rd Route 155") -- see its docstring for the exact
    rules distinguishing a genuine alias from ordinary extra words (like
    "Business" in "Business Route 4") that aren't one.

    Returns (prefix_directional, street_name, road_type, suffix_directional,
    alias).
    """
    text = clean_whitespace((text or "").upper().replace(".", ""))
    prefix_directional, remainder = parse_prefix_directional(text, only_if_more_follows=True)

    highway_result = parse_highway(remainder)
    if highway_result:
        street_name, suffix_directional, alias = highway_result
        return prefix_directional, street_name, None, suffix_directional, alias

    street_name, road_type, suffix_directional = parse_street_remainder(
        remainder, known_road_type, known_suffix_directional, only_abbreviated_suffix=True
    )
    return prefix_directional, street_name, road_type, suffix_directional, None


# ---------------------------------------------------------------------------
# FME Form (PythonCaller) integration
# ---------------------------------------------------------------------------
#
# Different input feature types name -- and split up -- their address
# columns differently, so every address-role parameter below is optional and
# independent; supply whichever ones exist on a given feature type and leave
# the rest blank ("") -- there is no required combination.
#
# PythonCaller's "Class to Process Features" parameter does not expose a
# class's __init__ arguments as transformer-dialog parameters -- there is no
# such dialog. Instead, paste a small wrapper script directly into the
# PythonCaller (see the README's "Using from FME Form" section for the exact
# script) that downloads this module from GitHub at runtime and instantiates
# `AddressCleaner` with the column-mapping arguments hardcoded as literal
# strings in that pasted script; set "Class to Process Features" to
# `AddressCleaner`, matching the wrapper class's name. The parameters, in
# order, along with three examples of what each one holds
# for the same three example features (a rural VT Route address, an in-town
# address, and a camp-lot address with a number prefix):
#
#                             | "2729 VT Route 114 S" | "137 E Main St"  | "H 5 Stonehedge Dr"
#   --------------------------|------------------------|------------------|--------------------
#   FullAddress               | "2729 VT Route 114 S,  | "137 E Main St,  | "H 5 Stonehedge Dr,
#                             |  Norton, VT 05907"     |  Hyde Park, VT   |  South Burlington,
#                             |                        |  05655"          |  VT 05403"
#   PrimaryAddress            | "2729 VT route 114 S"  | "137 E Main St"  | "H 5 Stonehedge Drive"
#
#   If FullAddress/PrimaryAddress aren't available in full, the address is
#   built from these individual fields instead:
#
#   PrimaryName               | "VT Route 114 S"       | "E Main St"      | "Stonehedge Drive"
#   StreetName                | (alternative to PrimaryName, when the bare
#                             |  name is already split from its directional/
#                             |  road type in its own dedicated column)
#   AddressNumber             | "2729"                 | "137"            | "5"
#   AddressNumber_LowRange    | (alternative to AddressNumber, when only a
#   AddressNumber_HighRange   |  low/high range is available, e.g. a road-
#                             |  centerline segment)
#   AddressNumber_Prefix      | ""                     | ""               | "H"
#   AddressNumber_Suffix      | ""                     | ""               | ""
#   Street_PreDirectional     | ""                     | "E"              | ""
#   Street_PostDirectional    | "S"                    | ""               | ""
#   Street_PostType           | ""                     | "St"             | "Drive"
#
# `PrimaryName`, if supplied, is always parsed the same way a combined
# string would be -- picking up its own prefix directional, route phrase,
# road type, and suffix directional -- so it can hold either just the bare
# name (e.g. "Stonehedge Drive") or the whole remainder (e.g. "E Main St").
# Whenever `Street_PreDirectional` / `Street_PostDirectional` /
# `Street_PostType` are also explicitly supplied, they take precedence over
# whatever was auto-detected from `PrimaryName`, so partially redundant data
# (as in the second example above, where "E Main St" and "St" are both
# given) is handled the same as fully split data. All three examples above
# standardize to:
#   "2729 VT ROUTE 114 S", "137 EAST MAIN STREET", "H5 STONEHEDGE DRIVE"
#
# `StreetName` is a separate, dedicated bare-name-only field -- distinct from
# `PrimaryName`, which may hold either the bare name or the full remainder --
# for a source system that already keeps the name split from its
# directional/type (e.g. a `St_Name`-style column). It applies no
# directional/road-type stripping of its own (there's nothing to strip out of
# a field guaranteed to be name-only) and, when supplied, takes precedence
# over whatever `PrimaryName` would otherwise auto-detect for the name
# portion.
#
# The secondary/unit address roles follow the same combined-vs-split pattern:
#
#   AddressSecondaryAddress        A combined secondary/unit address, e.g.
#                                   "Apt 1". Highest priority for the
#                                   secondary address; if set, the two
#                                   parameters below are ignored.
#   AddressSecondaryAbbreviation   e.g. "Apt".
#   AddressSecondaryNumber_LowRange     Low/high end of a secondary-unit
#   AddressSecondaryNumber_HighRange    number range preserved in separate
#                                       columns; used when
#                                       `AddressSecondaryAddress` is blank.
#
#   OutputAttributePrefix      Optional prefix applied to every attribute
#                               this transformer writes back (e.g. "MAIL_"),
#                               useful if the same transformer runs more than
#                               once in one workspace against different
#                               address roles. Replaces the default "Clean_"
#                               marker entirely -- it never stacks on top of
#                               it (e.g. "MAIL_STREET_NAME", never
#                               "MAIL_Clean_STREET_NAME").
#
# Output naming mirrors the input: for every role parameter that's given an
# attribute name, the output includes a `Clean_<that name>` attribute (e.g.
# `PrimaryName="STREET_NAME"` produces `Clean_STREET_NAME`), or
# `OutputAttributePrefix<that name>` if `OutputAttributePrefix` is set.
# `PrimaryName`, `StreetName`,
# `AddressNumber`, `Street_PreDirectional`, `Street_PostDirectional`,
# `Street_PostType`, and `AddressSecondaryAddress` are *always* produced
# this way -- falling back to their own parameter name (e.g.
# `Clean_PrimaryName`) when that role wasn't directly configured -- so the
# full breakdown is always available regardless of which tier of input was
# used: supply a combined `PrimaryName` and you still get
# `Clean_AddressNumber` / `Clean_Street_PreDirectional` / etc. back; supply
# only granular fields and you still get a `Clean_PrimaryName` built from
# them. `Clean_FullAddress` /
# `Clean_PrimaryAddress` are the exception: since they're strictly combined
# views, they're only produced when `FullAddress` / `PrimaryAddress` was
# itself supplied.
#
# A highway address (Interstate/Route) sometimes also carries a local alias
# road name -- e.g. "Tinmouth Rd" in "VT Route 133 W Tinmouth Rd", or
# "Weston Rd" in "Weston Rd Route 155" (the alias may come before or after
# the highway). When one is detected, it's split out into its own always-on
# `Clean_Alias` output (no dedicated input parameter of its own to
# configure), leaving the highway phrase alone in `Clean_PrimaryName` /
# `Clean_StreetName` / etc. Not every trailing/leading word next to a
# highway number is an alias, though -- "Central" in "VT Route 7B Central",
# "Business" in "Business Route 4", and "Old" in "Old Route 110" are just
# part of the highway's own name (no road type of their own), so they're
# left alone rather than split out; `Clean_Alias` is None in those cases.
#
# This module only standardizes address *numbers* and *street names* -- it
# never inspects or cleans city, state, or zip/zip+4 values, beyond
# recognizing and discarding a trailing city/state/zip tail on
# `FullAddress` so it doesn't get mistaken for part of the street. See the
# README for a full worked example of all three sample features.

def _build_secondary_from_parts(
    address: str,
    abbreviation: str,
    number_low: str,
    number_high: str,
) -> Optional[str]:
    """Build a standardized secondary/unit segment from whichever of a
    combined secondary-address string or a split abbreviation/number-range
    are available. Returns None if none of them are populated."""
    if address:
        _, secondary = extract_secondary_unit(clean_whitespace(address.upper().replace(".", "")))
        return secondary

    if abbreviation or number_low or number_high:
        keyword = SECONDARY_UNIT_MAP.get(abbreviation.strip().upper(), "UNIT")
        value = combine_number_range(number_low, number_high)
        return f"{keyword} {value}".strip() if value else keyword

    return None


def _build_primary_from_parts(
    primary_name: str,
    street_name: str,
    address_number: str,
    address_number_low: str,
    address_number_high: str,
    address_number_prefix: str,
    address_number_suffix: str,
    street_pre_directional: str,
    street_post_directional: str,
    street_post_type: str,
) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Build the five primary-address segments from whichever granular
    fields are available. `PrimaryName`, if given, is always parsed the same
    way a combined string would be -- picking up its own prefix directional,
    route phrase, road type, and suffix directional -- so it can hold either
    just the bare name (e.g. "Stonehedge Drive" when `Street_PostType` is
    also given) or the whole remainder (e.g. "E Main St"). Whenever
    `street_pre_directional` / `street_post_directional` / `street_post_type`
    are explicitly supplied, they take precedence over whatever was
    auto-detected from `PrimaryName`, so partially redundant data is handled
    the same as fully split data.

    `street_name`, if given, is a dedicated bare-name-only field (e.g. a
    `St_Name`-style column that's already guaranteed to hold nothing but the
    name, with no directional or road type of its own) -- it's normalized
    directly via `normalize_street_name()` with no further stripping, and
    takes precedence over whatever `PrimaryName` would otherwise auto-detect,
    since it's a more authoritative signal than text that still has to be
    parsed. If `primary_name` (or a highway phrase within it) carries a
    local alias road name -- see `parse_highway()` -- it's returned
    separately as `alias`, alongside the regular segments. Returns
    (address_number, prefix_directional, street_name, road_type,
    suffix_directional, alias); any that have no corresponding input are
    None."""
    base_number = normalize_address_number_token(address_number) if address_number else combine_number_range(
        address_number_low, address_number_high
    )
    number = _merge_address_number_parts(address_number_prefix, base_number, address_number_suffix)

    explicit_road_type = normalize_road_type(street_post_type)
    explicit_suffix_dir = normalize_suffix_directional(street_post_directional)

    auto_prefix_dir, auto_name, auto_road_type, auto_suffix_dir, alias = None, None, None, None, None
    if primary_name:
        auto_prefix_dir, auto_name, auto_road_type, auto_suffix_dir, alias = parse_primary_remainder(
            primary_name, known_road_type=explicit_road_type, known_suffix_directional=explicit_suffix_dir
        )

    name = normalize_street_name(street_name) or auto_name
    prefix_dir = normalize_prefix_directional(street_pre_directional) or auto_prefix_dir
    road_type = explicit_road_type or auto_road_type
    suffix_dir = explicit_suffix_dir or auto_suffix_dir
    return number, prefix_dir, name, road_type, suffix_dir, alias


def standardize_feature_attributes(
    attributes: Dict[str, Any],
    FullAddress: str = "",
    PrimaryAddress: str = "",
    PrimaryName: str = "",
    StreetName: str = "",
    AddressNumber: str = "",
    AddressNumber_LowRange: str = "",
    AddressNumber_HighRange: str = "",
    AddressNumber_Prefix: str = "",
    AddressNumber_Suffix: str = "",
    Street_PreDirectional: str = "",
    Street_PostDirectional: str = "",
    Street_PostType: str = "",
    AddressSecondaryAddress: str = "",
    AddressSecondaryAbbreviation: str = "",
    AddressSecondaryNumber_LowRange: str = "",
    AddressSecondaryNumber_HighRange: str = "",
    OutputAttributePrefix: str = "",
) -> Dict[str, Any]:
    """Build the standardized-address output attributes for one feature from
    whichever address-role attributes are configured (see the module-level
    comment above for what each parameter means and the README for a full
    worked example). Every parameter is optional and independent -- there is
    no required combination, and a feature with none of them configured
    simply yields an empty result.

    `attributes` is a plain dict of the feature's existing attribute values.
    Each parameter names one of those existing attributes; pass "" for
    whichever role doesn't apply to this feature type.

    The output mirrors the input: for every role parameter that was given an
    attribute name, the output includes a `Clean_<that name>` attribute
    holding the cleaned value for that same role (e.g. `PrimaryName="STREET"`
    produces `Clean_STREET`). `PrimaryName`, `StreetName`, `AddressNumber`,
    `Street_PreDirectional`, `Street_PostDirectional`, `Street_PostType`, and
    `AddressSecondaryAddress` are *always* included in the output this way --
    using their own parameter name (e.g. `Clean_PrimaryName`) as a fallback
    whenever that particular role wasn't directly configured -- so the full
    breakdown is available regardless of which tier of input was actually
    used: supply a combined `PrimaryName` and you still get
    `Clean_AddressNumber` / `Clean_Street_PreDirectional` / etc. back;
    supply only the granular fields and you still get a `Clean_PrimaryName`
    built from them. `StreetName` is a separate, dedicated bare-name-only
    field -- distinct from `PrimaryName`, which may hold either the bare name
    or the full remainder -- for a source system that already keeps the name
    split from its directional/type (e.g. a `St_Name`-style column); when
    supplied, it takes precedence over whatever `PrimaryName` would
    otherwise auto-detect for the name portion. `Clean_FullAddress` /
    `Clean_PrimaryAddress` are the exception: since they're strictly
    combined views, they're only produced when `FullAddress` /
    `PrimaryAddress` was itself supplied, rather than being invented a name
    for when it wasn't.

    A highway address (Interstate/Route) sometimes also carries a local
    alias road name, e.g. "Tinmouth Rd" in "VT Route 133 W Tinmouth Rd", or
    "Weston Rd" in "Weston Rd Route 155". When one is detected -- see
    `parse_highway()` for exactly what does and doesn't qualify as a genuine
    alias -- it's split out into its own always-on `Clean_Alias` output
    (no dedicated input parameter of its own), leaving the highway phrase
    alone in `Clean_PrimaryName` / `Clean_StreetName` / etc.

    Every output attribute name is marked with a `Clean_` prefix by default;
    if `OutputAttributePrefix` is set, it replaces that default marker
    entirely (it never stacks on top of it), ready to be merged back onto
    the feature's attributes.
    """

    def _get(attr_name: str) -> str:
        return (attributes.get(attr_name) or "") if attr_name.strip() else ""

    secondary_address = _build_secondary_from_parts(
        _get(AddressSecondaryAddress),
        _get(AddressSecondaryAbbreviation),
        _get(AddressSecondaryNumber_LowRange),
        _get(AddressSecondaryNumber_HighRange),
    )

    if FullAddress.strip() or PrimaryAddress.strip():
        combined = _get(FullAddress) or _get(PrimaryAddress)
        blended_text = strip_city_state_zip(clean_whitespace(combined.upper().replace(".", "")))
        segments = standardize_address(blended_text)["parsed_segments"]
        number, prefix_dir, name, road_type, suffix_dir, alias = (
            segments["address_number"], segments["prefix_directional"], segments["street_name"],
            segments["road_type"], segments["suffix_directional"], segments["alias"],
        )
        if secondary_address is None:
            secondary_address = segments["secondary_address"]
    else:
        number, prefix_dir, name, road_type, suffix_dir, alias = _build_primary_from_parts(
            _get(PrimaryName), _get(StreetName),
            _get(AddressNumber), _get(AddressNumber_LowRange), _get(AddressNumber_HighRange),
            _get(AddressNumber_Prefix), _get(AddressNumber_Suffix),
            _get(Street_PreDirectional), _get(Street_PostDirectional), _get(Street_PostType),
        )

    name_only = " ".join(part for part in (prefix_dir, name, road_type, suffix_dir) if part) or None
    primary_address = " ".join(part for part in (number, prefix_dir, name, road_type, suffix_dir) if part) or None
    full_address = primary_address
    if secondary_address:
        full_address = f"{primary_address}, {secondary_address}" if primary_address else secondary_address

    flat: Dict[str, Any] = {}
    marker = OutputAttributePrefix or "Clean_"

    def emit(configured_name: str, canonical_name: str, value: Optional[str]) -> None:
        flat[f"{marker}{(configured_name.strip() or canonical_name)}"] = value

    if FullAddress.strip():
        emit(FullAddress, "FullAddress", full_address)
    if PrimaryAddress.strip():
        emit(PrimaryAddress, "PrimaryAddress", primary_address)
    emit(PrimaryName, "PrimaryName", name_only)
    emit(StreetName, "StreetName", name)
    emit(AddressNumber, "AddressNumber", number)
    emit(Street_PreDirectional, "Street_PreDirectional", prefix_dir)
    emit(Street_PostDirectional, "Street_PostDirectional", suffix_dir)
    emit(Street_PostType, "Street_PostType", road_type)
    emit(AddressSecondaryAddress, "AddressSecondaryAddress", secondary_address)
    emit("", "Alias", alias)

    return flat


class AddressCleaner:
    """FME PythonCaller "Class" transformer wrapping `standardize_address()`.

    See the module-level comment above for how to wire this into a
    PythonCaller and what each constructor parameter configures.
    """

    def __init__(
        self,
        FullAddress: str = "",
        PrimaryAddress: str = "",
        PrimaryName: str = "",
        StreetName: str = "",
        AddressNumber: str = "",
        AddressNumber_LowRange: str = "",
        AddressNumber_HighRange: str = "",
        AddressNumber_Prefix: str = "",
        AddressNumber_Suffix: str = "",
        Street_PreDirectional: str = "",
        Street_PostDirectional: str = "",
        Street_PostType: str = "",
        AddressSecondaryAddress: str = "",
        AddressSecondaryAbbreviation: str = "",
        AddressSecondaryNumber_LowRange: str = "",
        AddressSecondaryNumber_HighRange: str = "",
        OutputAttributePrefix: str = "",
    ) -> None:
        self.FullAddress = FullAddress
        self.PrimaryAddress = PrimaryAddress
        self.PrimaryName = PrimaryName
        self.StreetName = StreetName
        self.AddressNumber = AddressNumber
        self.AddressNumber_LowRange = AddressNumber_LowRange
        self.AddressNumber_HighRange = AddressNumber_HighRange
        self.AddressNumber_Prefix = AddressNumber_Prefix
        self.AddressNumber_Suffix = AddressNumber_Suffix
        self.Street_PreDirectional = Street_PreDirectional
        self.Street_PostDirectional = Street_PostDirectional
        self.Street_PostType = Street_PostType
        self.AddressSecondaryAddress = AddressSecondaryAddress
        self.AddressSecondaryAbbreviation = AddressSecondaryAbbreviation
        self.AddressSecondaryNumber_LowRange = AddressSecondaryNumber_LowRange
        self.AddressSecondaryNumber_HighRange = AddressSecondaryNumber_HighRange
        self.OutputAttributePrefix = OutputAttributePrefix

    def input(self, feature: Any) -> None:
        attributes = {name: feature.getAttribute(name) for name in feature.getAllAttributeNames()}
        output = standardize_feature_attributes(
            attributes,
            self.FullAddress,
            self.PrimaryAddress,
            self.PrimaryName,
            self.StreetName,
            self.AddressNumber,
            self.AddressNumber_LowRange,
            self.AddressNumber_HighRange,
            self.AddressNumber_Prefix,
            self.AddressNumber_Suffix,
            self.Street_PreDirectional,
            self.Street_PostDirectional,
            self.Street_PostType,
            self.AddressSecondaryAddress,
            self.AddressSecondaryAbbreviation,
            self.AddressSecondaryNumber_LowRange,
            self.AddressSecondaryNumber_HighRange,
            self.OutputAttributePrefix,
        )
        # FME's setAttribute treats a bare None as "remove this attribute"
        # rather than "set it to a blank value" -- so a segment that
        # couldn't be determined for a given feature would otherwise vanish
        # from the output entirely instead of showing up as an empty
        # string, inconsistent with segments that did resolve to a value.
        for key, value in output.items():
            feature.setAttribute(key, value if value is not None else "")
        self.pyoutput(feature)

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cases = [
        ("123   N Main   St",
         "123 NORTH MAIN STREET"),
        ("33 1 / 2 St. Johnsbury Rd",
         "33 1/2 SAINT JOHNSBURY ROAD"),
        ("I-89 E",
         "INTERSTATE 89 E"),
        ("28-B Route 2",
         "28B US ROUTE 2"),
        ("1st st south, apt #4",
         "FIRST STREET S, UNIT 4"),
        ("POB 123",
         "PO BOX 123"),
        ("133 S Burlington St",
         "133 SOUTH BURLINGTON STREET"),
        ("VT Route 22A W",
         "VT ROUTE 22A W"),
        ("PO BOX 45, Ste # 2",
         "PO BOX 45, UNIT 2"),
        ("123 St Paul St",
         "123 SAINT PAUL STREET"),
        ("44-A N. Main st E., apt# 3",
         "44A NORTH MAIN STREET E, UNIT 3"),
        ("123 Main Street",
         "123 MAIN STREET"),
        ("88 South Hill Rd   ",
         "88 SOUTH HILL ROAD"),
        ("2896 Canaan Hill Rd",
         "2896 CANAAN HILL ROAD"),
        ("Route 2A",
         "VT ROUTE 2A"),
        ("RTE 2",
         "US ROUTE 2"),
        ("Route 7B",
         "VT ROUTE 7B"),
        ("26 G ST",
         "26 G STREET"),
        ("26 G St N",
         "26 G STREET N"),
        ("5 E St",
         "5 E STREET"),
        ("48 16 Outerbay Way",
         "48 16 OUTERBAY WAY"),
        ("64 A Frame Dr",
         "64A FRAME DRIVE"),
        ("VT Route 133 W Tinmouth Rd",
         "VT ROUTE 133 W"),
        ("VT Route 133 Morgan Rd",
         "VT ROUTE 133"),
        ("Weston Rd Route 155",
         "VT ROUTE 155"),
        ("VT Route 7B Central",
         "VT ROUTE 7B CENTRAL"),
        ("Business Route 4",
         "BUSINESS ROUTE 4"),
        ("Old Route 110",
         "OLD ROUTE 110"),
        ("VT Route 7B N Ext",
         "VT ROUTE 7B N EXTENSION"),
    ]

    for raw, expected_full in cases:
        result = standardize_address(raw)
        actual = result["full_address"]
        assert actual == expected_full, (
            f"FAILED for {raw!r}: expected {expected_full!r}, got {actual!r}\n{result}"
        )
        print(f"OK: {raw!r:45} -> {actual!r}")

    # Graceful handling of a missing secondary unit.
    result = standardize_address("123 Main Street")
    assert result["parsed_segments"]["secondary_address"] is None

    # A highway address sometimes also carries a local alias road name --
    # split out into its own "alias" segment, separate from the highway
    # phrase itself, rather than either being dropped or left glued onto it.
    result = standardize_address("VT Route 133 W Tinmouth Rd")
    assert result["parsed_segments"]["street_name"] == "VT ROUTE 133"
    assert result["parsed_segments"]["suffix_directional"] == "W"
    assert result["parsed_segments"]["alias"] == "TINMOUTH ROAD"

    result = standardize_address("VT Route 133 Morgan Rd")
    assert result["parsed_segments"]["alias"] == "MORGAN ROAD"

    # The alias can come before the highway instead of after it.
    result = standardize_address("Weston Rd Route 155")
    assert result["parsed_segments"]["street_name"] == "VT ROUTE 155"
    assert result["parsed_segments"]["alias"] == "WESTON ROAD"

    # Extra words next to a highway number aren't always an alias -- only a
    # genuine "name plus its own road type" qualifies. A bare descriptive
    # word with no road type of its own (e.g. "Central") is just part of the
    # highway's own name, not a separate alias, and isn't dropped either.
    for raw in ("VT Route 7B Central", "Business Route 4", "Old Route 110"):
        result = standardize_address(raw)
        assert result["parsed_segments"]["alias"] is None, raw

    # "Ext" is fully spelled out as "Extension" for a route the same as any
    # other road type, and isn't mistaken for an alias either (a bare road
    # type with no name of its own is a route modifier, not a separate
    # road).
    result = standardize_address("VT Route 7B N Ext")
    assert result["parsed_segments"]["street_name"] == "VT ROUTE 7B N EXTENSION"
    assert result["parsed_segments"]["alias"] is None

    # A true full mailing address carries a city/state/zip tail that this
    # module doesn't touch -- it should be recognized and dropped.
    result = standardize_address("3 E Main St N, South Burlington, VT 05403")
    assert result["full_address"] == "3 EAST MAIN STREET N"

    # A single letter isn't always an address-number suffix (e.g. "28-A"
    # merging to "28A") -- it can be a legitimate stand-alone single-letter
    # street name (e.g. "G Street"). Only merge the letter into the number
    # when something more than a bare road type actually follows it.
    result = standardize_address("26 G ST")
    assert result["parsed_segments"]["address_number"] == "26"
    assert result["parsed_segments"]["street_name"] == "G"
    assert result["parsed_segments"]["road_type"] == "STREET"
    assert result["full_address"] == "26 G STREET"

    # --- FME attribute-mapping wrapper ---------------------------------
    #
    # Output attribute names mirror whatever attribute name was configured
    # for each role (e.g. PrimaryName="STREET_NAME" -> "Clean_STREET_NAME"),
    # falling back to that role's own canonical name (e.g. "PrimaryName")
    # when it wasn't directly configured. PrimaryName / AddressNumber /
    # Street_PreDirectional / Street_PostDirectional / Street_PostType /
    # AddressSecondaryAddress are *always* produced this way, regardless of
    # which tier of input was actually used -- so a combined PrimaryName
    # input still yields the full segment breakdown, and fully granular
    # input still yields a constructed Clean_PrimaryName.

    # Three worked examples (see the README): a rural VT Route address, an
    # in-town address, and a camp-lot address with a number prefix. Each is
    # exercised through all three levels of field availability, checking
    # both the combined result and the individual segment breakdown.
    worked_examples = [
        {
            "FullAddress": "2729 VT Route 114 S, Norton, VT 05907",
            "PrimaryAddress": "2729 VT route 114 S",
            "PrimaryName": "VT Route 114 S",
            "AddressNumber": "2729",
            "AddressNumber_Prefix": "",
            "AddressNumber_Suffix": "",
            "Street_PreDirectional": "",
            "Street_PostDirectional": "South",
            "Street_PostType": "",
            "expected": "2729 VT ROUTE 114 S",
            "expected_number": "2729",
            "expected_name_only": "VT ROUTE 114 S",
            "expected_street_name": "VT ROUTE 114",
            "expected_prefix_dir": None,
            "expected_road_type": None,
            "expected_suffix_dir": "S",
        },
        {
            "FullAddress": "137 E Main St, Hyde Park, VT 05655",
            "PrimaryAddress": "137 E Main St",
            "PrimaryName": "E Main St",
            "AddressNumber": "137",
            "AddressNumber_Prefix": "",
            "AddressNumber_Suffix": "",
            "Street_PreDirectional": "E",
            "Street_PostDirectional": "",
            "Street_PostType": "St",
            "expected": "137 EAST MAIN STREET",
            "expected_number": "137",
            "expected_name_only": "EAST MAIN STREET",
            "expected_street_name": "MAIN",
            "expected_prefix_dir": "EAST",
            "expected_road_type": "STREET",
            "expected_suffix_dir": None,
        },
        {
            "FullAddress": "H 5 Stonehedge Dr, South Burlington, VT 05403",
            "PrimaryAddress": "H 5 Stonehedge Drive",
            "PrimaryName": "Stonehedge Drive",
            "AddressNumber": "5",
            "AddressNumber_Prefix": "H",
            "AddressNumber_Suffix": "",
            "Street_PreDirectional": "",
            "Street_PostDirectional": "",
            "Street_PostType": "Drive",
            "expected": "H5 STONEHEDGE DRIVE",
            "expected_number": "H5",
            "expected_name_only": "STONEHEDGE DRIVE",
            "expected_street_name": "STONEHEDGE",
            "expected_prefix_dir": None,
            "expected_road_type": "DRIVE",
            "expected_suffix_dir": None,
        },
    ]

    def _assert_breakdown(out, ex, label):
        assert out["Clean_PrimaryName"] == ex["expected_name_only"], (
            f"{label} FAILED for {ex}: Clean_PrimaryName got {out.get('Clean_PrimaryName')!r}"
        )
        assert out["Clean_StreetName"] == ex["expected_street_name"], (
            f"{label} FAILED for {ex}: Clean_StreetName got {out.get('Clean_StreetName')!r}"
        )
        assert out["Clean_AddressNumber"] == ex["expected_number"], (
            f"{label} FAILED for {ex}: Clean_AddressNumber got {out.get('Clean_AddressNumber')!r}"
        )
        assert out["Clean_Street_PreDirectional"] == ex["expected_prefix_dir"], (
            f"{label} FAILED for {ex}: Clean_Street_PreDirectional got {out.get('Clean_Street_PreDirectional')!r}"
        )
        assert out["Clean_Street_PostType"] == ex["expected_road_type"], (
            f"{label} FAILED for {ex}: Clean_Street_PostType got {out.get('Clean_Street_PostType')!r}"
        )
        assert out["Clean_Street_PostDirectional"] == ex["expected_suffix_dir"], (
            f"{label} FAILED for {ex}: Clean_Street_PostDirectional got {out.get('Clean_Street_PostDirectional')!r}"
        )

    for ex in worked_examples:
        # Tier 1: FullAddress (city/state/zip tail dropped automatically).
        # Configuring FullAddress alone still yields the full breakdown.
        out = standardize_feature_attributes({"F": ex["FullAddress"]}, FullAddress="F")
        assert out["Clean_F"] == ex["expected"], (
            f"FullAddress FAILED for {ex['FullAddress']!r}: got {out.get('Clean_F')!r}"
        )
        assert "Clean_PrimaryAddress" not in out  # wasn't configured -- not fabricated
        _assert_breakdown(out, ex, "FullAddress")

        # Tier 2: PrimaryAddress (no city/state/zip to begin with).
        out = standardize_feature_attributes({"P": ex["PrimaryAddress"]}, PrimaryAddress="P")
        assert out["Clean_P"] == ex["expected"], (
            f"PrimaryAddress FAILED for {ex['PrimaryAddress']!r}: got {out.get('Clean_P')!r}"
        )
        assert "Clean_FullAddress" not in out
        _assert_breakdown(out, ex, "PrimaryAddress")

        # Tier 3: individual building-block fields. No FullAddress/
        # PrimaryAddress was given, so neither combined key is produced,
        # but Clean_PrimaryName is still built from the granular pieces --
        # using its own configured name here ("N").
        out = standardize_feature_attributes(
            {
                "N": ex["PrimaryName"],
                "NUM": ex["AddressNumber"],
                "NUMPRE": ex["AddressNumber_Prefix"],
                "NUMSUF": ex["AddressNumber_Suffix"],
                "PRE": ex["Street_PreDirectional"],
                "POST": ex["Street_PostDirectional"],
                "TYPE": ex["Street_PostType"],
            },
            PrimaryName="N",
            AddressNumber="NUM",
            AddressNumber_Prefix="NUMPRE",
            AddressNumber_Suffix="NUMSUF",
            Street_PreDirectional="PRE",
            Street_PostDirectional="POST",
            Street_PostType="TYPE",
        )
        assert "Clean_FullAddress" not in out and "Clean_PrimaryAddress" not in out
        assert out["Clean_N"] == ex["expected_name_only"]
        assert out["Clean_StreetName"] == ex["expected_street_name"]
        assert out["Clean_NUM"] == ex["expected_number"]
        assert out["Clean_PRE"] == ex["expected_prefix_dir"]
        assert out["Clean_TYPE"] == ex["expected_road_type"]
        assert out["Clean_POST"] == ex["expected_suffix_dir"]
        print(f"OK: {ex['expected']!r:30} <- FullAddress / PrimaryAddress / building blocks")

    # Full combined column, with a city/state/zip tail to strip and a
    # secondary unit embedded within it. Output mirrors the configured
    # attribute name ("SITE_ADDRESS").
    out = standardize_feature_attributes(
        {"SITE_ADDRESS": "133 S Burlington St, Apt 4, South Burlington, VT 05403"},
        FullAddress="SITE_ADDRESS",
    )
    assert out["Clean_SITE_ADDRESS"] == "133 SOUTH BURLINGTON STREET, UNIT 4"
    assert out["Clean_AddressSecondaryAddress"] == "UNIT 4"

    # Primary/secondary already split across two combined columns, with an
    # output prefix applied to every attribute this call produces.
    out = standardize_feature_attributes(
        {"MAIL_PRIMARY": "88 South Hill Rd", "MAIL_UNIT": "Ste 2"},
        PrimaryAddress="MAIL_PRIMARY",
        AddressSecondaryAddress="MAIL_UNIT",
        OutputAttributePrefix="MAIL_STD_",
    )
    assert out["MAIL_STD_MAIL_PRIMARY"] == "88 SOUTH HILL ROAD"
    assert out["MAIL_STD_MAIL_UNIT"] == "UNIT 2"
    assert out["MAIL_STD_Street_PostType"] == "ROAD"
    # OutputAttributePrefix replaces the default "Clean_" marker entirely --
    # it never stacks on top of it (e.g. never "MAIL_STD_Clean_...").
    assert not any(key.startswith("MAIL_STD_Clean_") for key in out)

    # A stand-alone single-letter street name (e.g. "G Street") isn't
    # mistaken for a "26-G"-style alphanumeric address-number suffix.
    out = standardize_feature_attributes({"ADDR": "26 G ST"}, PrimaryAddress="ADDR")
    assert out["Clean_ADDR"] == "26 G STREET"
    assert out["Clean_AddressNumber"] == "26"
    assert out["Clean_StreetName"] == "G"
    assert out["Clean_Street_PostType"] == "STREET"

    # A stand-alone single-letter street name that also happens to be a
    # cardinal direction (e.g. "E Street") isn't mistaken for a prefix
    # directional attached to the following road type. This is specific to
    # the granular PrimaryName path (no address number mixed in, unlike
    # PrimaryAddress/FullAddress, which still treat a leading single-letter
    # abbreviation as an unconditional prefix directional per rule 5).
    out = standardize_feature_attributes({"N": "E ST"}, PrimaryName="N")
    assert out["Clean_N"] == "E STREET"
    assert out["Clean_Street_PreDirectional"] is None
    assert out["Clean_StreetName"] == "E"
    assert out["Clean_Street_PostType"] == "STREET"

    # A two-part whole-number address number (e.g. rural/lot-style
    # addressing) is kept together as the address number, with a space,
    # rather than the second number leaking into the street name.
    out = standardize_feature_attributes({"ADDR": "48 16 Outerbay Way"}, PrimaryAddress="ADDR")
    assert out["Clean_ADDR"] == "48 16 OUTERBAY WAY"
    assert out["Clean_AddressNumber"] == "48 16"
    assert out["Clean_StreetName"] == "OUTERBAY"
    assert out["Clean_Street_PostType"] == "WAY"

    # ... but a bare second number followed by nothing but a road type is
    # left alone, since it could instead be a legitimate numbered street
    # name (e.g. "5 42 St" -- house number 5 on a street literally named
    # "42", not address number "5 42").
    out = standardize_feature_attributes({"ADDR": "5 42 St"}, PrimaryAddress="ADDR")
    assert out["Clean_AddressNumber"] == "5"
    assert out["Clean_StreetName"] == "42"

    # Address number preserved as a low/high range across two columns
    # (e.g. a road-centerline segment), with no single AddressNumber --
    # Clean_AddressNumber still falls back to its canonical name since the
    # AddressNumber parameter itself wasn't configured.
    out = standardize_feature_attributes(
        {"LOW": "1", "HIGH": "5", "NAME": "Main St"},
        AddressNumber_LowRange="LOW",
        AddressNumber_HighRange="HIGH",
        PrimaryName="NAME",
    )
    assert "Clean_FullAddress" not in out and "Clean_PrimaryAddress" not in out
    assert out["Clean_AddressNumber"] == "1-5"
    assert out["Clean_NAME"] == "MAIN STREET"

    # Half-value number built from a split AddressNumber + AddressNumber_Suffix.
    out = standardize_feature_attributes(
        {"NUM": "33", "SUF": "1/2", "NAME": "Main St"},
        AddressNumber="NUM", AddressNumber_Suffix="SUF", PrimaryName="NAME",
    )
    assert out["Clean_NUM"] == "33 1/2"
    assert out["Clean_NAME"] == "MAIN STREET"

    # A word that's also a valid road type (Hill, Lake, ...) but is really
    # part of the street name must not be stripped out just because
    # PrimaryName's last token happens to match ROAD_TYPE_MAP -- the
    # explicitly-given Street_PostType is what's authoritative, and it
    # doesn't match "Hill", so "Hill" stays part of the name.
    out = standardize_feature_attributes(
        {"NAME": "Canaan Hill", "NUM": "2896", "TYPE": "Rd"},
        PrimaryName="NAME", AddressNumber="NUM", Street_PostType="TYPE",
    )
    assert out["Clean_StreetName"] == "CANAAN HILL"
    assert out["Clean_TYPE"] == "ROAD"

    out = standardize_feature_attributes(
        {"NAME": "Lake Morey", "NUM": "10", "TYPE": "Rd"},
        PrimaryName="NAME", AddressNumber="NUM", Street_PostType="TYPE",
    )
    assert out["Clean_StreetName"] == "LAKE MOREY"
    assert out["Clean_TYPE"] == "ROAD"

    # ... but when the trailing word genuinely is a redundant duplicate of
    # the explicit road type (as opposed to coincidentally matching a
    # different one), it's still correctly treated as redundant and
    # dropped from the name, same as before this fix.
    out = standardize_feature_attributes(
        {"NAME": "E Main St", "NUM": "137", "PRE": "E", "TYPE": "St"},
        PrimaryName="NAME", AddressNumber="NUM",
        Street_PreDirectional="PRE", Street_PostType="TYPE",
    )
    assert out["Clean_StreetName"] == "MAIN"
    assert out["Clean_TYPE"] == "STREET"

    # The same ambiguity applies to a trailing directional *word* (e.g.
    # "West" in "Old West") -- it must not be stripped out as a suffix
    # directional just because PrimaryName's last token happens to be a
    # directional word, when there's no Street_PostDirectional confirming
    # it's actually one.
    out = standardize_feature_attributes(
        {"NAME": "Old West", "NUM": "123"},
        PrimaryName="NAME", AddressNumber="NUM",
    )
    assert out["Clean_StreetName"] == "OLD WEST"
    assert out["Clean_Street_PostDirectional"] is None

    # A single-letter abbreviation is still unambiguous and gets stripped
    # even with no Street_PostDirectional to confirm it.
    out = standardize_feature_attributes(
        {"NAME": "Main St S", "NUM": "137"},
        PrimaryName="NAME", AddressNumber="NUM",
    )
    assert out["Clean_StreetName"] == "MAIN"
    assert out["Clean_Street_PostDirectional"] == "S"

    # ... and a trailing word that genuinely is a redundant duplicate of an
    # explicitly-given Street_PostDirectional is still dropped, same as the
    # analogous road-type case above.
    out = standardize_feature_attributes(
        {"NAME": "Main St South", "NUM": "137", "POST": "South"},
        PrimaryName="NAME", AddressNumber="NUM", Street_PostDirectional="POST",
    )
    assert out["Clean_StreetName"] == "MAIN"
    assert out["Clean_POST"] == "S"

    # Secondary unit built from a split abbreviation + number range instead
    # of one combined secondary-address column -- canonical fallback name
    # since AddressSecondaryAddress itself wasn't configured.
    out = standardize_feature_attributes(
        {"UNIT_TYPE": "Apt", "UNIT_LOW": "1", "UNIT_HIGH": "5"},
        AddressSecondaryAbbreviation="UNIT_TYPE",
        AddressSecondaryNumber_LowRange="UNIT_LOW",
        AddressSecondaryNumber_HighRange="UNIT_HIGH",
    )
    assert out["Clean_AddressSecondaryAddress"] == "UNIT 1-5"

    # StreetName is a separate, dedicated bare-name-only field, distinct
    # from PrimaryName -- for a source system that already keeps the name
    # split from its directional/type in its own column.
    out = standardize_feature_attributes(
        {"NAME": "Main", "NUM": "137", "PRE": "E", "TYPE": "St"},
        StreetName="NAME", AddressNumber="NUM",
        Street_PreDirectional="PRE", Street_PostType="TYPE",
    )
    assert out["Clean_NAME"] == "MAIN"
    assert out["Clean_PrimaryName"] == "EAST MAIN STREET"
    assert out["Clean_NUM"] == "137"

    # When both StreetName and PrimaryName are supplied, StreetName -- the
    # more authoritative, already-split signal -- wins for the name portion.
    out = standardize_feature_attributes(
        {"BARE": "Main", "FULL": "E Main St"},
        StreetName="BARE", PrimaryName="FULL",
    )
    assert out["Clean_BARE"] == "MAIN"
    assert out["Clean_FULL"] == "EAST MAIN STREET"

    # A highway alias splits into its own always-on Clean_Alias output,
    # separate from Clean_PrimaryName -- whether the alias comes after the
    # highway or before it -- with no dedicated input parameter of its own.
    out = standardize_feature_attributes(
        {"NAME": "VT Route 133 W Tinmouth Rd"}, PrimaryName="NAME"
    )
    assert out["Clean_NAME"] == "VT ROUTE 133 W"
    assert out["Clean_Alias"] == "TINMOUTH ROAD"

    out = standardize_feature_attributes({"NAME": "Weston Rd Route 155"}, PrimaryName="NAME")
    assert out["Clean_NAME"] == "VT ROUTE 155"
    assert out["Clean_Alias"] == "WESTON ROAD"

    # Extra words next to a highway number that don't form a genuine
    # "name plus road type" aren't mistaken for an alias.
    for raw in ("VT Route 7B Central", "Business Route 4", "Old Route 110"):
        out = standardize_feature_attributes({"NAME": raw}, PrimaryName="NAME")
        assert out["Clean_NAME"] == raw.upper(), raw
        assert out["Clean_Alias"] is None, raw

    # No address-role attributes configured at all -> graceful empty
    # result, never an error (no combination is a strict requirement).
    # Clean_FullAddress / Clean_PrimaryAddress are never fabricated, but
    # the always-on segments (using their canonical names) are still
    # present, just holding None.
    out = standardize_feature_attributes({})
    assert "Clean_FullAddress" not in out and "Clean_PrimaryAddress" not in out
    assert out["Clean_PrimaryName"] is None
    assert out["Clean_AddressNumber"] is None
    assert out["Clean_AddressSecondaryAddress"] is None
    assert out["Clean_Alias"] is None

    print("\nAll assertions passed.")
