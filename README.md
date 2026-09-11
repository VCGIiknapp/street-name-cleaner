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

Different feature types name their address columns differently, and not
every dataset splits a full/primary/secondary address the same way (or has
all three at all). Rather than hardcoding column names, wire this module's
`AddressCleaner` class into a **PythonCaller** transformer set to "Class"
mode:

```
Class or Function to Process Features: street_name_cleaner.AddressCleaner
```

FME reads the class's constructor parameters and exposes each one as a
transformer parameter, so the column mapping is a dialog setting, not code:

| Parameter | Meaning |
| --- | --- |
| `full_address_attr` | Input attribute holding a full/combined address string (e.g. `SITE_ADDRESS`), if this feature type has one. |
| `primary_address_attr` | Input attribute holding just the primary/street address, if the dataset keeps it separate from the unit. |
| `secondary_address_attr` | Input attribute holding just the secondary/unit address, if the dataset keeps it separate. |
| `output_attr_prefix` | Optional prefix applied to every output attribute (e.g. `MAIL_`), useful if the transformer runs more than once in one workspace against different address roles. |

Leave whichever address-role parameters don't apply blank; at least one of
`full_address_attr` / `primary_address_attr` / `secondary_address_attr` must
be set, or the transformer raises an error at workspace startup. The
transformer writes back `full_address_caps`, `full_address_title`, and every
key from `standardize_address()`'s `parsed_segments` (optionally prefixed)
onto each feature.

The same logic is available outside of FME via
`standardize_feature_attributes(attributes, ...)`, which takes a plain
`dict` of attribute values and returns the flat output dict, for testing or
use in other pipelines.
