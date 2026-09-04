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
