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

# Words that should stay fully uppercase when producing a Title Case string
# (initialisms), in addition to alphanumeric address/route numbers.
KEEP_UPPER_WORDS = {"PO", "US", "VT"}
ALPHANUMERIC_TOKEN_RE = re.compile(r"^\d+[A-Z]+$")


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

def extract_address_number(text: str) -> tuple[Optional[str], str]:
    """Pull a leading house number off `text`, honoring half-value and
    alphanumeric formatting rules. Returns (address_number, remainder)."""
    # Half value, e.g. "33 1/2 Main St" -> "33 1/2"
    match = re.match(r"^(\d+)\s+(\d+/\d+)\b\s*", text)
    if match:
        number = f"{match.group(1)} {match.group(2)}"
        return number, text[match.end():]

    # Alphanumeric, e.g. "28-A" / "28 A" -> "28A". A lone N/S/E/W is never
    # merged in here since that's a directional word, not a unit letter.
    match = re.match(r"^(\d+)[\s-]?([A-Za-z])\b\s*", text)
    if match and match.group(2).upper() not in PREFIX_DIRECTIONAL_MAP:
        number = f"{match.group(1)}{match.group(2).upper()}"
        return number, text[match.end():]

    # Plain number
    match = re.match(r"^(\d+)\b\s*", text)
    if match:
        return match.group(1), text[match.end():]

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


def parse_street_remainder(remainder: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Parse whatever's left of a primary address after the address number
    and prefix directional (if any) have already been pulled off (or, when
    called directly on a bare street-name string that may still carry its
    own suffix/directional, the whole thing): extracts a trailing road type
    and/or suffix directional, expands ordinals, and disambiguates a leading
    "ST" as "SAINT". Returns (street_name, road_type, suffix_directional)."""
    remainder = clean_whitespace((remainder or "").upper().replace(".", ""))
    tokens = [t for t in remainder.split(" ") if t]
    tokens = [expand_ordinal_token(t) for t in tokens]

    suffix_directional, tokens = parse_suffix_directional(tokens)

    road_type = None
    if tokens and tokens[-1] in ROAD_TYPE_MAP:
        road_type = ROAD_TYPE_MAP[tokens[-1]]
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
# Title casing
# ---------------------------------------------------------------------------

def title_case_address(text: Optional[str]) -> Optional[str]:
    """Title-case a caps address string while preserving initialisms
    (PO/US/VT) and alphanumeric numbers (e.g. "28A") exactly as-is."""
    if not text:
        return text
    words = text.split(" ")
    out = []
    for word in words:
        core = word.rstrip(",")
        suffix = word[len(core):]
        if ALPHANUMERIC_TOKEN_RE.match(core) or core.upper() in KEEP_UPPER_WORDS:
            out.append(core + suffix)
        else:
            out.append(core.capitalize() + suffix)
    return " ".join(out)


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
        "full_address_title": title_case_address(full_address_caps) or None,
        "parsed_segments": {
            "primary_address_caps": primary_address_caps or None,
            "primary_address_title": title_case_address(primary_address_caps) or None,
            "address_number_caps": address_number,
            "prefix_directional_caps": prefix_directional,
            "street_name_caps": street_name,
            "road_type_caps": road_type,
            "suffix_directional_caps": suffix_directional,
            "secondary_address_caps": secondary_address,
            "secondary_address_title": title_case_address(secondary_address),
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


def _process_bare_street_name(text: str) -> tuple[Optional[str], Optional[str]]:
    """Expand ordinals, disambiguate a leading "ST" as "SAINT", and spell out
    any embedded directional in a street name that is already known to be
    free of its road type (supplied separately). Opportunistically detects a
    trailing suffix directional too, for callers that don't have that as its
    own separate field. Returns (street_name, suffix_directional)."""
    text = clean_whitespace((text or "").upper().replace(".", ""))
    tokens = [t for t in text.split(" ") if t]
    if not tokens:
        return None, None

    tokens = [expand_ordinal_token(t) for t in tokens]
    suffix_directional, tokens = parse_suffix_directional(tokens)

    if tokens and tokens[0] == "ST":
        tokens[0] = "SAINT"

    tokens = [PREFIX_DIRECTIONAL_MAP.get(t, t) for t in tokens]

    street_name = " ".join(tokens) if tokens else None
    return street_name, suffix_directional


# ---------------------------------------------------------------------------
# FME Form (PythonCaller) integration
# ---------------------------------------------------------------------------
#
# Different input feature types name -- and split up -- their address
# columns differently, so every address-role attribute below is optional and
# independent; supply whichever ones exist on a given feature type and leave
# the rest blank ("") -- there is no required combination. Wire this
# module's `AddressCleaner` class into a PythonCaller transformer set to
# "Class" mode:
#
#   Class or Function to Process Features: street_name_cleaner.AddressCleaner
#
# FME reads `AddressCleaner.__init__`'s parameters and exposes each one as a
# transformer parameter, so the column mapping is a dialog setting, not code:
#
#   full_address_attr          A full/combined address string that may still
#                               carry a trailing city/state/zip (e.g.
#                               "3 E Main St N, South Burlington, VT 05403");
#                               that tail is dropped automatically. Highest
#                               priority: if set, every other primary-address
#                               parameter below is ignored.
#   primary_address_attr       A combined primary (street) address with no
#                               city/state/zip, e.g. "3 E Main St N". Used
#                               when `full_address_attr` is blank; if set, the
#                               granular fields below are ignored.
#   street_name_attr           Just the street name, e.g. "Main St" (may or
#                               may not include the suffix -- see
#                               `street_suffix_attr`) or "Main".
#   address_number_attr        A single house number, e.g. "3".
#   address_number_low_attr    Low end of an address-number range preserved
#   address_number_high_attr   in separate columns (e.g. road-centerline
#                               segments); used when `address_number_attr` is
#                               blank.
#   prefix_directional_attr    e.g. "E".
#   street_suffix_attr         e.g. "St". When set, `street_name_attr` is
#                               treated as the bare name (no suffix).
#   post_directional_attr      e.g. "N".
#   secondary_address_attr     A combined secondary/unit address, e.g.
#                               "Apt 1". Highest priority for the secondary
#                               address; if set, the two parameters below are
#                               ignored.
#   secondary_abbreviation_attr    e.g. "Apt".
#   secondary_number_low_attr      Low/high end of a secondary-unit number
#   secondary_number_high_attr     range preserved in separate columns; used
#                                   when `secondary_address_attr` is blank.
#   output_attr_prefix          Optional prefix applied to every attribute
#                               this transformer writes back (e.g. "MAIL_"),
#                               useful if the same transformer runs more than
#                               once in one workspace against different
#                               address roles.
#
# This module only standardizes address *numbers* and *street names* -- it
# never inspects or cleans city, state, or zip/zip+4 values, beyond
# recognizing and discarding a trailing city/state/zip tail on
# `full_address_attr` so it doesn't get mistaken for part of the street.

def _build_secondary_from_parts(
    secondary_address: str,
    secondary_abbreviation: str,
    secondary_number_low: str,
    secondary_number_high: str,
) -> Optional[str]:
    """Build a standardized secondary/unit segment from whichever of a
    combined secondary-address string or a split abbreviation/number-range
    are available. Returns None if none of them are populated."""
    if secondary_address:
        _, secondary = extract_secondary_unit(clean_whitespace(secondary_address.upper().replace(".", "")))
        return secondary

    if secondary_abbreviation or secondary_number_low or secondary_number_high:
        keyword = SECONDARY_UNIT_MAP.get(secondary_abbreviation.strip().upper(), "UNIT")
        value = combine_number_range(secondary_number_low, secondary_number_high)
        return f"{keyword} {value}".strip() if value else keyword

    return None


def _build_primary_from_parts(
    address_number: str,
    address_number_low: str,
    address_number_high: str,
    prefix_directional: str,
    street_name: str,
    street_suffix: str,
    post_directional: str,
) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Build the five primary-address segments from whichever granular
    fields are available. Returns
    (address_number, prefix_directional, street_name, road_type,
    suffix_directional); any that have no corresponding input are None."""
    number = normalize_address_number_token(address_number) if address_number else combine_number_range(
        address_number_low, address_number_high
    )
    prefix_dir = normalize_prefix_directional(prefix_directional)

    auto_suffix_dir = None
    if street_suffix:
        # Suffix supplied separately: the name field is just the bare name.
        road_type = normalize_road_type(street_suffix)
        name, auto_suffix_dir = _process_bare_street_name(street_name)
    elif street_name:
        # No separate suffix: the name field may itself carry a trailing
        # road type and/or directional (e.g. "Main St" or "Main St N").
        name, road_type, auto_suffix_dir = parse_street_remainder(street_name)
    else:
        name, road_type = None, None

    suffix_dir = normalize_suffix_directional(post_directional) or auto_suffix_dir
    return number, prefix_dir, name, road_type, suffix_dir


def standardize_feature_attributes(
    attributes: Dict[str, Any],
    full_address_attr: str = "",
    primary_address_attr: str = "",
    street_name_attr: str = "",
    address_number_attr: str = "",
    address_number_low_attr: str = "",
    address_number_high_attr: str = "",
    prefix_directional_attr: str = "",
    street_suffix_attr: str = "",
    post_directional_attr: str = "",
    secondary_address_attr: str = "",
    secondary_abbreviation_attr: str = "",
    secondary_number_low_attr: str = "",
    secondary_number_high_attr: str = "",
    output_attr_prefix: str = "",
) -> Dict[str, Any]:
    """Build the standardized-address output attributes for one feature from
    whichever address-role attributes are configured (see the module-level
    comment above for what each parameter means). Every parameter is
    optional and independent -- there is no required combination, and a
    feature with none of them configured simply yields an empty result.

    `attributes` is a plain dict of the feature's existing attribute values.
    Each `..._attr` parameter names one of those existing attributes; pass
    "" for whichever role doesn't apply to this feature type.

    Returns a flat dict -- `standardize_address()`'s two top-level keys plus
    its `parsed_segments`, optionally prefixed with `output_attr_prefix` --
    ready to be merged back onto the feature's attributes.
    """

    def _get(attr_name: str) -> str:
        return (attributes.get(attr_name) or "") if attr_name.strip() else ""

    secondary_address = _build_secondary_from_parts(
        _get(secondary_address_attr),
        _get(secondary_abbreviation_attr),
        _get(secondary_number_low_attr),
        _get(secondary_number_high_attr),
    )

    if full_address_attr.strip() or primary_address_attr.strip():
        combined = _get(full_address_attr) or _get(primary_address_attr)
        blended_text = strip_city_state_zip(clean_whitespace(combined.upper().replace(".", "")))
        blended = standardize_address(blended_text)
        segments = dict(blended["parsed_segments"])
        primary_address_caps = segments["primary_address_caps"] or ""
        if secondary_address is None:
            secondary_address = segments["secondary_address_caps"]
    else:
        number, prefix_dir, name, road_type, suffix_dir = _build_primary_from_parts(
            _get(address_number_attr), _get(address_number_low_attr), _get(address_number_high_attr),
            _get(prefix_directional_attr), _get(street_name_attr), _get(street_suffix_attr),
            _get(post_directional_attr),
        )
        primary_address_caps = " ".join(part for part in (number, prefix_dir, name, road_type, suffix_dir) if part)
        segments = {
            "address_number_caps": number,
            "prefix_directional_caps": prefix_dir,
            "street_name_caps": name,
            "road_type_caps": road_type,
            "suffix_directional_caps": suffix_dir,
        }

    segments["primary_address_caps"] = primary_address_caps or None
    segments["primary_address_title"] = title_case_address(primary_address_caps) or None
    segments["secondary_address_caps"] = secondary_address
    segments["secondary_address_title"] = title_case_address(secondary_address)

    full_address_caps = primary_address_caps
    if secondary_address:
        full_address_caps = f"{primary_address_caps}, {secondary_address}" if primary_address_caps else secondary_address

    flat = {"full_address_caps": full_address_caps or None, "full_address_title": title_case_address(full_address_caps) or None}
    flat.update(segments)

    if output_attr_prefix:
        flat = {f"{output_attr_prefix}{key}": value for key, value in flat.items()}
    return flat


class AddressCleaner:
    """FME PythonCaller "Class" transformer wrapping `standardize_address()`.

    See the module-level comment above for how to wire this into a
    PythonCaller and what each constructor parameter configures.
    """

    def __init__(
        self,
        full_address_attr: str = "",
        primary_address_attr: str = "",
        street_name_attr: str = "",
        address_number_attr: str = "",
        address_number_low_attr: str = "",
        address_number_high_attr: str = "",
        prefix_directional_attr: str = "",
        street_suffix_attr: str = "",
        post_directional_attr: str = "",
        secondary_address_attr: str = "",
        secondary_abbreviation_attr: str = "",
        secondary_number_low_attr: str = "",
        secondary_number_high_attr: str = "",
        output_attr_prefix: str = "",
    ) -> None:
        self.full_address_attr = full_address_attr
        self.primary_address_attr = primary_address_attr
        self.street_name_attr = street_name_attr
        self.address_number_attr = address_number_attr
        self.address_number_low_attr = address_number_low_attr
        self.address_number_high_attr = address_number_high_attr
        self.prefix_directional_attr = prefix_directional_attr
        self.street_suffix_attr = street_suffix_attr
        self.post_directional_attr = post_directional_attr
        self.secondary_address_attr = secondary_address_attr
        self.secondary_abbreviation_attr = secondary_abbreviation_attr
        self.secondary_number_low_attr = secondary_number_low_attr
        self.secondary_number_high_attr = secondary_number_high_attr
        self.output_attr_prefix = output_attr_prefix

    def input(self, feature: Any) -> None:
        attributes = {name: feature.getAttribute(name) for name in feature.getAllAttributeNames()}
        output = standardize_feature_attributes(
            attributes,
            self.full_address_attr,
            self.primary_address_attr,
            self.street_name_attr,
            self.address_number_attr,
            self.address_number_low_attr,
            self.address_number_high_attr,
            self.prefix_directional_attr,
            self.street_suffix_attr,
            self.post_directional_attr,
            self.secondary_address_attr,
            self.secondary_abbreviation_attr,
            self.secondary_number_low_attr,
            self.secondary_number_high_attr,
            self.output_attr_prefix,
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
    assert result["parsed_segments"]["secondary_address_title"] is None

    # Title Case output, incl. the "28A" alphanumeric-stays-capitalized rule.
    assert standardize_address("88 South Hill Rd   ")["full_address_title"] == "88 South Hill Road"
    assert standardize_address("28-A Main St")["parsed_segments"]["primary_address_title"] == "28A Main Street"

    # A true full mailing address carries a city/state/zip tail that this
    # module doesn't touch -- it should be recognized and dropped.
    result = standardize_address("3 E Main St N, South Burlington, VT 05403")
    assert result["full_address_caps"] == "3 EAST MAIN STREET N"

    # --- FME attribute-mapping wrapper ---------------------------------

    # Full combined column, with a city/state/zip tail to strip.
    out = standardize_feature_attributes(
        {"SITE_ADDRESS": "133 S Burlington St, Apt 4, South Burlington, VT 05403"},
        full_address_attr="SITE_ADDRESS",
    )
    assert out["full_address_caps"] == "133 SOUTH BURLINGTON STREET, UNIT 4"
    assert out["secondary_address_caps"] == "UNIT 4"

    # Primary/secondary already split across two combined columns.
    out = standardize_feature_attributes(
        {"MAIL_PRIMARY": "88 South Hill Rd", "MAIL_UNIT": "Ste 2"},
        primary_address_attr="MAIL_PRIMARY",
        secondary_address_attr="MAIL_UNIT",
        output_attr_prefix="MAIL_STD_",
    )
    assert out["MAIL_STD_full_address_caps"] == "88 SOUTH HILL ROAD, UNIT 2"
    assert out["MAIL_STD_road_type_caps"] == "ROAD"

    # Fully split NENA/USPS-style fields: bare street name + separate
    # suffix + separate pre/post directionals + a single house number.
    out = standardize_feature_attributes(
        {
            "ADDNUM": "3",
            "PREDIR": "E",
            "STREETNAME": "Main",
            "SUFFIX": "St",
            "POSTDIR": "N",
        },
        address_number_attr="ADDNUM",
        prefix_directional_attr="PREDIR",
        street_name_attr="STREETNAME",
        street_suffix_attr="SUFFIX",
        post_directional_attr="POSTDIR",
    )
    assert out["full_address_caps"] == "3 EAST MAIN STREET N"
    assert out["road_type_caps"] == "STREET"
    assert out["suffix_directional_caps"] == "N"

    # Street name field that still carries its own suffix (no separate
    # suffix column) is auto-split the same way a blended string would be.
    out = standardize_feature_attributes(
        {"NAME": "Main St"}, street_name_attr="NAME",
    )
    assert out["street_name_caps"] == "MAIN"
    assert out["road_type_caps"] == "STREET"

    # Address number preserved as a low/high range across two columns
    # (e.g. a road-centerline segment), with no single AddressNumber.
    out = standardize_feature_attributes(
        {"LOW": "1", "HIGH": "5", "NAME": "Main", "SUFFIX": "St"},
        address_number_low_attr="LOW",
        address_number_high_attr="HIGH",
        street_name_attr="NAME",
        street_suffix_attr="SUFFIX",
    )
    assert out["address_number_caps"] == "1-5"
    assert out["full_address_caps"] == "1-5 MAIN STREET"

    # Secondary unit built from a split abbreviation + number range instead
    # of one combined secondary-address column.
    out = standardize_feature_attributes(
        {"UNIT_TYPE": "Apt", "UNIT_LOW": "1", "UNIT_HIGH": "5"},
        secondary_abbreviation_attr="UNIT_TYPE",
        secondary_number_low_attr="UNIT_LOW",
        secondary_number_high_attr="UNIT_HIGH",
    )
    assert out["secondary_address_caps"] == "UNIT 1-5"

    # No address-role attributes configured at all -> graceful empty
    # result, never an error (no combination is a strict requirement).
    out = standardize_feature_attributes({})
    assert out["full_address_caps"] is None
    assert out["address_number_caps"] is None

    print("\nAll assertions passed.")
