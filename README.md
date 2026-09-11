# street-name-cleaner

Standardizes US address formats for Vermont E911 data.

`street_name_cleaner.py` is a self-contained Python module (standard library
only) that parses a raw address string and returns a structured, normalized
result following Vermont-specific business rules for:

- Whitespace cleanup
- PO Box formatting
- Secondary/unit designators (Apt, Ste, Room, etc. -> `UNIT`)
- Address number formatting, including half values (`33 1/2`) and
  alphanumeric numbers (`28A`)
- Ordinal street names (`1st` -> `FIRST`)
- `St` as `Saint` vs. `Street` disambiguation
- Street suffix expansion (`Rd` -> `ROAD`, etc.)
- Prefix/suffix directional handling (`N` -> `NORTH`, suffix directionals
  stay abbreviated, e.g. `ROUTE 30 E`)
- Interstate, US Route, and VT Route classification/formatting

Its reference tables (street-type abbreviations, directionals, route
classifications) were derived from a one-time offline survey of Vermont's
four VCGI/E911 ArcGIS REST FeatureServer endpoints (road centerlines,
driveways, site/structure address points, hydrants) and a USPS ZIP+4
reference extract for Vermont, so the module has no runtime network or file
dependencies.

## Usage

```python
from street_name_cleaner import standardize_address

result = standardize_address("123 N Main St")
print(result["full_address_caps"])   # "123 NORTH MAIN STREET"
print(result["full_address_title"])  # "123 North Main Street"
```

`standardize_address()` returns:

```python
{
    "full_address_caps": "...",
    "full_address_title": "...",
    "parsed_segments": {
        "primary_address_caps": "...",
        "primary_address_title": "...",
        "address_number_caps": "...",
        "prefix_directional_caps": "...",
        "street_name_caps": "...",
        "road_type_caps": "...",
        "suffix_directional_caps": "...",
        "secondary_address_caps": "...",
        "secondary_address_title": "...",
    },
}
```

Intended to be imported as a library (e.g. from an FME Workspace Python
Caller / Custom Transformer) to clean full, primary, and secondary address
columns.

## Testing

```
python street_name_cleaner.py
```

Runs the module's built-in `assert`-based test suite covering documented
edge cases.

## Using from FME Form

Different feature types name -- and split up -- their address columns very
differently: some hand you one complete mailing address string, some split
primary/secondary into two columns, and some (like Vermont's E911 road
centerline/address point data) split everything down to individual
NENA/USPS fields, sometimes even preserving a low/high address-number range
across two columns instead of a single house number. Rather than hardcoding
column names, wire this module's `AddressCleaner` class into a
**PythonCaller** transformer set to "Class" mode:

```
Class or Function to Process Features: street_name_cleaner.AddressCleaner
```

FME reads the class's constructor parameters and exposes each one as a
transformer parameter, so the column mapping is a dialog setting, not code.
Every parameter is optional and independent -- supply whichever ones exist
on a given feature type and leave the rest blank; there is no required
combination:

| Parameter | Meaning |
| --- | --- |
| `full_address_attr` | A full/combined address string that may still carry a trailing city/state/zip (e.g. `"3 E Main St N, South Burlington, VT 05403"`); that tail is dropped automatically. Highest priority: if set, every other primary-address parameter is ignored. |
| `primary_address_attr` | A combined primary (street) address with no city/state/zip, e.g. `"3 E Main St N"`. Used when `full_address_attr` is blank; if set, the granular fields below are ignored. |
| `street_name_attr` | Just the street name, e.g. `"Main St"` (may or may not include the suffix -- see `street_suffix_attr`) or `"Main"`. |
| `address_number_attr` | A single house number, e.g. `"3"`. |
| `address_number_low_attr` / `address_number_high_attr` | Low/high end of an address-number range preserved in separate columns (e.g. road-centerline segments); used when `address_number_attr` is blank. |
| `prefix_directional_attr` | e.g. `"E"`. |
| `street_suffix_attr` | e.g. `"St"`. When set, `street_name_attr` is treated as the bare name (no suffix). |
| `post_directional_attr` | e.g. `"N"`. |
| `secondary_address_attr` | A combined secondary/unit address, e.g. `"Apt 1"`. Highest priority for the secondary address; if set, the two parameters below are ignored. |
| `secondary_abbreviation_attr` | e.g. `"Apt"`. |
| `secondary_number_low_attr` / `secondary_number_high_attr` | Low/high end of a secondary-unit number range preserved in separate columns; used when `secondary_address_attr` is blank. |
| `output_attr_prefix` | Optional prefix applied to every attribute this transformer writes back (e.g. `MAIL_`), useful if the same transformer runs more than once in one workspace against different address roles. |

A feature type with none of these configured simply yields an empty result
-- never an error. The transformer writes back `full_address_caps`,
`full_address_title`, and every key from `standardize_address()`'s
`parsed_segments` (optionally prefixed) onto each feature.

This module only standardizes address *numbers* and *street names*; it
never inspects or cleans city, state, or zip/zip+4 values, beyond
recognizing and discarding a trailing city/state/zip tail on
`full_address_attr` so it doesn't get mistaken for part of the street.

The same logic is available outside of FME via
`standardize_feature_attributes(attributes, ...)`, which takes a plain
`dict` of attribute values and returns the flat output dict, for testing or
use in other pipelines.
