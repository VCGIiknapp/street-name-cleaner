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
# the VCGI road centerline / address point / hydrant layers (which also
# surfaced a few abbreviations, e.g. CIRS, not present in the USPS extract).
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

# Non-highway address prefixes (rule 5). Highway-specific "Route"/"Rt"/"Rte"
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
            tokens = [t for t in remainder.split(" ") if t]
            tokens = [expand_ordinal_token(t) for t in tokens]

            suffix_directional, tokens = parse_suffix_directional(tokens)

            if tokens and tokens[-1] in ROAD_TYPE_MAP:
                road_type = ROAD_TYPE_MAP[tokens[-1]]
                tokens = tokens[:-1]

            if tokens and tokens[0] == "ST":
                tokens[0] = "SAINT"

            # Any directional word left inside the street name itself (i.e.
            # not the recognized prefix/suffix position) must be spelled out
            # in full, never abbreviated (rule 5).
            tokens = [PREFIX_DIRECTIONAL_MAP.get(t, t) for t in tokens]

            street_name = " ".join(tokens) if tokens else None

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

    print("\nAll assertions passed.")
