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
    string. Returns (remaining_primary_text, secondary_address_caps)."""
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

    # Alphanumeric, e.g. "28-A" / "28 A" -> "28A". A lone N/S/E/W is never
    # merged in here since that's a directional word, not a unit letter.
    match = re.match(r"^(\d+)[\s-]?([A-Za-z])\b\s*", body)
    if match and match.group(2).upper() not in PREFIX_DIRECTIONAL_MAP:
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
        base_num = _to_number(route_num)
        prefix = "US" if base_num in US_ROUTES else "VT"
        return f"{prefix} ROUTE {route_num}", remainder[match.end():].strip()

    return None, remainder


# ---------------------------------------------------------------------------
# Directional parsing
# ---------------------------------------------------------------------------

def parse_prefix_directional(remainder: str) -> tuple[Optional[str], str]:
    tokens = remainder.split(" ", 1)
    first = tokens[0] if tokens else ""
    if first in PREFIX_DIRECTIONAL_MAP:
        rest = tokens[1] if len(tokens) > 1 else ""
        return PREFIX_DIRECTIONAL_MAP[first], rest.strip()
    return None, remainder


def parse_suffix_directional(tokens: List[str]) -> tuple[Optional[str], List[str]]:
    """Extract a trailing cardinal suffix directional from a street-name
    token list. Requires at least one other token so a lone street name that
    happens to equal a directional word (unusual, but possible) isn't
    stripped down to nothing."""
    if tokens and tokens[-1] in SUFFIX_DIRECTIONAL_ABBR and len(tokens) > 1:
        return SUFFIX_DIRECTIONAL_ABBR[tokens[-1]], tokens[:-1]
    return None, tokens


def extract_trailing_directional(remainder: str) -> Optional[str]:
    """Extract a suffix directional from whatever text is left after an
    Interstate/Route phrase has been consumed (e.g. "E" in "I-89 E")."""
    remainder = remainder.strip()
    return SUFFIX_DIRECTIONAL_ABBR.get(remainder)


def parse_street_remainder(
    remainder: str, known_road_type: Optional[str] = None
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
    found in `ROAD_TYPE_MAP` is stripped, as before."""
    remainder = clean_whitespace((remainder or "").upper().replace(".", ""))
    tokens = [t for t in remainder.split(" ") if t]
    tokens = [expand_ordinal_token(t) for t in tokens]

    suffix_directional, tokens = parse_suffix_directional(tokens)

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
    # abbreviated (rule 5).
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

    po_box = parse_po_box(primary_text)
    interstate_or_route, route_remainder = standardize_highways(primary_text)

    if po_box:
        address_number = po_box["address_number"]
        street_name = po_box["street_name"]

    elif interstate_or_route:
        street_name = interstate_or_route
        suffix_directional = extract_trailing_directional(route_remainder)

    else:
        address_number, remainder = extract_address_number(primary_text)
        remainder = remainder.strip()

        if address_number:
            prefix_directional, remainder = parse_prefix_directional(remainder)

        route_phrase, route_rest = standardize_highways(remainder)
        if route_phrase:
            street_name = route_phrase
            suffix_directional = extract_trailing_directional(route_rest)
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
    primary_address_caps = " ".join(primary_parts) if primary_parts else ""

    full_address_caps = primary_address_caps
    if secondary_address:
        full_address_caps = f"{primary_address_caps}, {secondary_address}" if primary_address_caps else secondary_address

    result = {
        "full_address_caps": full_address_caps or None,
        "parsed_segments": {
            "primary_address_caps": primary_address_caps or None,
            "address_number_caps": address_number,
            "prefix_directional_caps": prefix_directional,
            "street_name_caps": street_name,
            "road_type_caps": road_type,
            "suffix_directional_caps": suffix_directional,
            "secondary_address_caps": secondary_address,
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
    text: str, known_road_type: Optional[str] = None
) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Parse a blended `PrimaryName`-style string -- the part of a primary
    address that comes after the address number, which may itself still
    carry a leading prefix directional (e.g. "E Main St") and/or a
    highway/route phrase, or an ordinary street name with a trailing road
    type / suffix directional. `known_road_type`, if given, is forwarded to
    `parse_street_remainder()` so an ambiguous trailing word (e.g. "Hill",
    "Lake") is only stripped out as a road type when it's redundant with
    that known value, rather than assumed to be one on its own. Returns
    (prefix_directional, street_name, road_type, suffix_directional)."""
    text = clean_whitespace((text or "").upper().replace(".", ""))
    prefix_directional, remainder = parse_prefix_directional(text)

    route_phrase, route_rest = standardize_highways(remainder)
    if route_phrase:
        return prefix_directional, route_phrase, None, extract_trailing_directional(route_rest)

    street_name, road_type, suffix_directional = parse_street_remainder(remainder, known_road_type)
    return prefix_directional, street_name, road_type, suffix_directional


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
#                               address roles.
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
    address_number: str,
    address_number_low: str,
    address_number_high: str,
    address_number_prefix: str,
    address_number_suffix: str,
    street_pre_directional: str,
    street_post_directional: str,
    street_post_type: str,
) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Build the five primary-address segments from whichever granular
    fields are available. `PrimaryName`, if given, is always parsed the same
    way a combined string would be -- picking up its own prefix directional,
    route phrase, road type, and suffix directional -- so it can hold either
    just the bare name (e.g. "Stonehedge Drive" when `Street_PostType` is
    also given) or the whole remainder (e.g. "E Main St"). Whenever
    `street_pre_directional` / `street_post_directional` / `street_post_type`
    are explicitly supplied, they take precedence over whatever was
    auto-detected from `PrimaryName`, so partially redundant data is handled
    the same as fully split data. Returns
    (address_number, prefix_directional, street_name, road_type,
    suffix_directional); any that have no corresponding input are None."""
    base_number = normalize_address_number_token(address_number) if address_number else combine_number_range(
        address_number_low, address_number_high
    )
    number = _merge_address_number_parts(address_number_prefix, base_number, address_number_suffix)

    explicit_road_type = normalize_road_type(street_post_type)

    auto_prefix_dir, name, auto_road_type, auto_suffix_dir = None, None, None, None
    if primary_name:
        auto_prefix_dir, name, auto_road_type, auto_suffix_dir = parse_primary_remainder(
            primary_name, known_road_type=explicit_road_type
        )

    prefix_dir = normalize_prefix_directional(street_pre_directional) or auto_prefix_dir
    road_type = explicit_road_type or auto_road_type
    suffix_dir = normalize_suffix_directional(street_post_directional) or auto_suffix_dir
    return number, prefix_dir, name, road_type, suffix_dir


def standardize_feature_attributes(
    attributes: Dict[str, Any],
    FullAddress: str = "",
    PrimaryAddress: str = "",
    PrimaryName: str = "",
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

    Outputs are a direct cleaning of whatever was actually supplied: the
    combined `full_address_caps` / `primary_address_caps` keys are only
    produced when `FullAddress` or `PrimaryAddress` was itself given (since
    only then is a combined address actually being cleaned, rather than
    invented from unrelated granular fields); otherwise the return value
    holds only the cleaned building-block segments -- `secondary_address_caps`
    is always included when any secondary-role field was supplied, whichever
    tier is otherwise in use -- optionally prefixed with
    `OutputAttributePrefix`, ready to be merged back onto the feature's
    attributes.
    """

    def _get(attr_name: str) -> str:
        return (attributes.get(attr_name) or "") if attr_name.strip() else ""

    secondary_address = _build_secondary_from_parts(
        _get(AddressSecondaryAddress),
        _get(AddressSecondaryAbbreviation),
        _get(AddressSecondaryNumber_LowRange),
        _get(AddressSecondaryNumber_HighRange),
    )

    combined_given = bool(FullAddress.strip() or PrimaryAddress.strip())
    if combined_given:
        combined = _get(FullAddress) or _get(PrimaryAddress)
        blended_text = strip_city_state_zip(clean_whitespace(combined.upper().replace(".", "")))
        blended = standardize_address(blended_text)
        segments = dict(blended["parsed_segments"])
        primary_address_caps = segments.pop("primary_address_caps") or ""
        if secondary_address is None:
            secondary_address = segments["secondary_address_caps"]
    else:
        number, prefix_dir, name, road_type, suffix_dir = _build_primary_from_parts(
            _get(PrimaryName),
            _get(AddressNumber), _get(AddressNumber_LowRange), _get(AddressNumber_HighRange),
            _get(AddressNumber_Prefix), _get(AddressNumber_Suffix),
            _get(Street_PreDirectional), _get(Street_PostDirectional), _get(Street_PostType),
        )
        primary_address_caps = " ".join(part for part in (number, prefix_dir, name, road_type, suffix_dir) if part)
        segments = {
            "address_number_caps": number,
            "prefix_directional_caps": prefix_dir,
            "street_name_caps": name,
            "road_type_caps": road_type,
            "suffix_directional_caps": suffix_dir,
        }

    segments["secondary_address_caps"] = secondary_address

    flat = dict(segments)
    if combined_given:
        full_address_caps = primary_address_caps
        if secondary_address:
            full_address_caps = f"{primary_address_caps}, {secondary_address}" if primary_address_caps else secondary_address
        flat["primary_address_caps"] = primary_address_caps or None
        flat["full_address_caps"] = full_address_caps or None

    if OutputAttributePrefix:
        flat = {f"{OutputAttributePrefix}{key}": value for key, value in flat.items()}
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
        for key, value in output.items():
            feature.setAttribute(key, value)
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
    ]

    for raw, expected_full_caps in cases:
        result = standardize_address(raw)
        actual = result["full_address_caps"]
        assert actual == expected_full_caps, (
            f"FAILED for {raw!r}: expected {expected_full_caps!r}, got {actual!r}\n{result}"
        )
        print(f"OK: {raw!r:45} -> {actual!r}")

    # Graceful handling of a missing secondary unit.
    result = standardize_address("123 Main Street")
    assert result["parsed_segments"]["secondary_address_caps"] is None

    # A true full mailing address carries a city/state/zip tail that this
    # module doesn't touch -- it should be recognized and dropped.
    result = standardize_address("3 E Main St N, South Burlington, VT 05403")
    assert result["full_address_caps"] == "3 EAST MAIN STREET N"

    # --- FME attribute-mapping wrapper ---------------------------------

    def _join_primary_segments(out):
        # Building-block-only input never produces full_address_caps /
        # primary_address_caps (see standardize_feature_attributes's
        # docstring), so tests on that path recombine the individual
        # segments themselves to check the parsing was correct.
        parts = (
            out.get("address_number_caps"),
            out.get("prefix_directional_caps"),
            out.get("street_name_caps"),
            out.get("road_type_caps"),
            out.get("suffix_directional_caps"),
        )
        return " ".join(part for part in parts if part)

    # Three worked examples (see the README): a rural VT Route address, an
    # in-town address, and a camp-lot address with a number prefix. Each is
    # exercised through all three levels of field availability.
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
        },
    ]

    for ex in worked_examples:
        # Tier 1: FullAddress (city/state/zip tail dropped automatically).
        out = standardize_feature_attributes({"F": ex["FullAddress"]}, FullAddress="F")
        assert out["full_address_caps"] == ex["expected"], (
            f"FullAddress FAILED for {ex['FullAddress']!r}: got {out['full_address_caps']!r}"
        )

        # Tier 2: PrimaryAddress (no city/state/zip to begin with).
        out = standardize_feature_attributes({"P": ex["PrimaryAddress"]}, PrimaryAddress="P")
        assert out["full_address_caps"] == ex["expected"], (
            f"PrimaryAddress FAILED for {ex['PrimaryAddress']!r}: got {out['full_address_caps']!r}"
        )

        # Tier 3: individual building-block fields. No FullAddress/
        # PrimaryAddress was given, so no combined key is produced --
        # outputs are only a direct cleaning of the granular inputs.
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
        assert "full_address_caps" not in out and "primary_address_caps" not in out, (
            f"Building blocks FAILED for {ex}: unexpected combined key in {out}"
        )
        assert _join_primary_segments(out) == ex["expected"], (
            f"Building blocks FAILED for {ex}: got {out}"
        )
        print(f"OK: {ex['expected']!r:30} <- FullAddress / PrimaryAddress / building blocks")

    # Full combined column, with a city/state/zip tail to strip and a
    # secondary unit embedded within it.
    out = standardize_feature_attributes(
        {"SITE_ADDRESS": "133 S Burlington St, Apt 4, South Burlington, VT 05403"},
        FullAddress="SITE_ADDRESS",
    )
    assert out["full_address_caps"] == "133 SOUTH BURLINGTON STREET, UNIT 4"
    assert out["secondary_address_caps"] == "UNIT 4"

    # Primary/secondary already split across two combined columns.
    out = standardize_feature_attributes(
        {"MAIL_PRIMARY": "88 South Hill Rd", "MAIL_UNIT": "Ste 2"},
        PrimaryAddress="MAIL_PRIMARY",
        AddressSecondaryAddress="MAIL_UNIT",
        OutputAttributePrefix="MAIL_STD_",
    )
    assert out["MAIL_STD_full_address_caps"] == "88 SOUTH HILL ROAD, UNIT 2"
    assert out["MAIL_STD_road_type_caps"] == "ROAD"

    # Address number preserved as a low/high range across two columns
    # (e.g. a road-centerline segment), with no single AddressNumber. No
    # combined column was given, so no combined key is produced.
    out = standardize_feature_attributes(
        {"LOW": "1", "HIGH": "5", "NAME": "Main St"},
        AddressNumber_LowRange="LOW",
        AddressNumber_HighRange="HIGH",
        PrimaryName="NAME",
    )
    assert "full_address_caps" not in out
    assert out["address_number_caps"] == "1-5"
    assert _join_primary_segments(out) == "1-5 MAIN STREET"

    # Half-value number built from a split AddressNumber + AddressNumber_Suffix.
    out = standardize_feature_attributes(
        {"NUM": "33", "SUF": "1/2", "NAME": "Main St"},
        AddressNumber="NUM", AddressNumber_Suffix="SUF", PrimaryName="NAME",
    )
    assert "full_address_caps" not in out
    assert _join_primary_segments(out) == "33 1/2 MAIN STREET"

    # A word that's also a valid road type (Hill, Lake, ...) but is really
    # part of the street name must not be stripped out just because
    # PrimaryName's last token happens to match ROAD_TYPE_MAP -- the
    # explicitly-given Street_PostType is what's authoritative, and it
    # doesn't match "Hill", so "Hill" stays part of the name.
    out = standardize_feature_attributes(
        {"NAME": "Canaan Hill", "NUM": "2896", "TYPE": "Rd"},
        PrimaryName="NAME", AddressNumber="NUM", Street_PostType="TYPE",
    )
    assert out["street_name_caps"] == "CANAAN HILL"
    assert out["road_type_caps"] == "ROAD"

    out = standardize_feature_attributes(
        {"NAME": "Lake Morey", "NUM": "10", "TYPE": "Rd"},
        PrimaryName="NAME", AddressNumber="NUM", Street_PostType="TYPE",
    )
    assert out["street_name_caps"] == "LAKE MOREY"
    assert out["road_type_caps"] == "ROAD"

    # ... but when the trailing word genuinely is a redundant duplicate of
    # the explicit road type (as opposed to coincidentally matching a
    # different one), it's still correctly treated as redundant and
    # dropped from the name, same as before this fix.
    out = standardize_feature_attributes(
        {"NAME": "E Main St", "NUM": "137", "PRE": "E", "TYPE": "St"},
        PrimaryName="NAME", AddressNumber="NUM",
        Street_PreDirectional="PRE", Street_PostType="TYPE",
    )
    assert out["street_name_caps"] == "MAIN"
    assert out["road_type_caps"] == "STREET"

    # Secondary unit built from a split abbreviation + number range instead
    # of one combined secondary-address column.
    out = standardize_feature_attributes(
        {"UNIT_TYPE": "Apt", "UNIT_LOW": "1", "UNIT_HIGH": "5"},
        AddressSecondaryAbbreviation="UNIT_TYPE",
        AddressSecondaryNumber_LowRange="UNIT_LOW",
        AddressSecondaryNumber_HighRange="UNIT_HIGH",
    )
    assert out["secondary_address_caps"] == "UNIT 1-5"

    # No address-role attributes configured at all -> graceful empty
    # result, never an error (no combination is a strict requirement), and
    # no combined keys since nothing combined was ever supplied.
    out = standardize_feature_attributes({})
    assert "full_address_caps" not in out and "primary_address_caps" not in out
    assert out["address_number_caps"] is None
    assert out["secondary_address_caps"] is None

    print("\nAll assertions passed.")
