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

## Examples

Every example below is taken directly from the module's self-test suite
(`python street_name_cleaner.py`), so this table is guaranteed to stay in
sync with what the code actually does.

| Input | `full_address_caps` output | Demonstrates |
| --- | --- | --- |
| `123   N Main   St` | `123 NORTH MAIN STREET` | Collapsing extra internal whitespace; `N` as a prefix directional |
| `33 1 / 2 St. Johnsbury Rd` | `33 1/2 SAINT JOHNSBURY ROAD` | Half-value spacing (`1 / 2` -> `1/2`); `St` as `SAINT` (a place name, not a road type) |
| `I-89 E` | `INTERSTATE 89 E` | Interstate spelled out in full; suffix directional stays abbreviated |
| `28-B Route 2` | `28B US ROUTE 2` | Alphanumeric merge (`28-B` -> `28B`); VT's US Routes list (2 is a US Route) |
| `1st st south, apt #4` | `FIRST STREET S, UNIT 4` | Ordinal expansion (`1st` -> `FIRST`); `st` as `STREET` (a road type here, not `SAINT`); suffix directional abbreviated; `apt #4` -> `UNIT 4` |
| `POB 123` | `PO BOX 123` | PO Box variant recognized and standardized |
| `133 S Burlington St` | `133 SOUTH BURLINGTON STREET` | Prefix directional spelled out in full (contrast with the suffix-directional cases above) |
| `VT Route 22A W` | `VT ROUTE 22A W` | VT Route with an alphanumeric route number, already-present `VT` prefix preserved |
| `PO BOX 45, Ste # 2` | `PO BOX 45, UNIT 2` | PO Box combined with a secondary unit; `#` stripped |
| `123 St Paul St` | `123 SAINT PAUL STREET` | `St` disambiguated two different ways in the same string: `SAINT` (place name) vs. `STREET` (road type) |
| `44-A N. Main st E., apt# 3` | `44A NORTH MAIN STREET E, UNIT 3` | Stress test: alphanumeric number, prefix directional, road type, suffix directional, and secondary unit all together |
| `123 Main Street` | `123 MAIN STREET` | Graceful handling when there's no secondary unit at all (`secondary_address_caps` is `None`) |
| `88 South Hill Rd` (with trailing spaces) | `88 SOUTH HILL ROAD` | Leading/trailing whitespace trimmed |
| `3 E Main St N, South Burlington, VT 05403` | `3 EAST MAIN STREET N` | A true full mailing address: trailing city/state/zip recognized and dropped automatically |

Two additional things the self-test verifies about the `..._title` (Title
Case) output:

| Input | Title Case output | Demonstrates |
| --- | --- | --- |
| `88 South Hill Rd` | `88 South Hill Road` (`full_address_title`) | Ordinary Title Case |
| `28-A Main St` | `28A Main Street` (`primary_address_title`) | Alphanumeric address numbers stay fully capitalized in Title Case (never `28a`) |

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
across two columns instead of a single house number, or a letter prefix on
the house number itself (rural VT camp/lot numbering, e.g. "H 5"). Rather
than hardcoding column names, wire this module's `AddressCleaner` class into
a **PythonCaller** transformer set to "Class" mode:

```
Class or Function to Process Features: street_name_cleaner.AddressCleaner
```

FME reads the class's constructor parameters and exposes each one as a
transformer parameter, so the column mapping is a dialog setting, not code.
Every parameter is optional and independent -- supply whichever ones exist
on a given feature type and leave the rest blank; **there is no required
combination.**

### Worked examples

The three examples below are used consistently throughout this section --
example 1, 2, and 3 always refer to the same three real-world features:

1. A rural VT Route address: **`2729 VT Route 114 S, Norton, VT 05907`**
2. An in-town address: **`137 E Main St, Hyde Park, VT 05655`**
3. A camp/lot address with a house-number prefix: **`H 5 Stonehedge Dr, South Burlington, VT 05403`**

All three standardize to:

| Example | Standardized `full_address_caps` |
| --- | --- |
| 1 | `2729 VT ROUTE 114 S` |
| 2 | `137 EAST MAIN STREET` |
| 3 | `H5 STONEHEDGE DRIVE` |

### Parameters, in order

**Tier 1 -- one combined field.** If either of these is available, use it;
`FullAddress` takes priority over `PrimaryAddress`, and every field below is
ignored.

| Parameter | Meaning | Example 1 | Example 2 | Example 3 |
| --- | --- | --- | --- | --- |
| `FullAddress` | A full/combined address string that may still carry a trailing city/state/zip. That tail is recognized and dropped automatically -- this module never otherwise touches city/state/zip. | `2729 VT Route 114 S, Norton, VT 05907` | `137 E Main St, Hyde Park, VT 05655` | `H 5 Stonehedge Dr, South Burlington, VT 05403` |
| `PrimaryAddress` | A combined primary (street) address with no city/state/zip. Used when `FullAddress` is blank. | `2729 VT route 114 S` | `137 E Main St` | `H 5 Stonehedge Drive` |

**Tier 2 -- building-block fields.** If neither field above is available,
the address is assembled from these instead:

| Parameter | Meaning | Example 1 | Example 2 | Example 3 |
| --- | --- | --- | --- | --- |
| `PrimaryName` | The street portion after the address number. Always parsed the same way a combined string would be -- picking up its own prefix directional, route phrase, road type, and suffix directional -- so it can hold just the bare name (example 3) or the whole remainder (example 2). | `VT Route 114 S` | `E Main St` | `Stonehedge Drive` |
| `AddressNumber` | A single house number. | `2729` | `137` | `5` |
| `AddressNumber_LowRange` | Low end of an address-number range, in its own column (e.g. a road-centerline segment); used when `AddressNumber` is blank. Not used in any of the three examples. | -- | -- | -- |
| `AddressNumber_HighRange` | High end of that same range, in a second, separate column. Not used in any of the three examples. | -- | -- | -- |
| `AddressNumber_Prefix` | A letter (or rural camp/lot word like "LOT"/"CABIN") immediately before the number, merged tight per rule 3 (`H` + `5` -> `H5`). | *(none)* | *(none)* | `H` |
| `AddressNumber_Suffix` | A letter suffix on the number, merged tight the same way (e.g. `A` -> `...28A`), or `1/2` for a half value (kept with a space: `33 1/2`). | *(none)* | *(none)* | *(none)* |
| `Street_PreDirectional` | e.g. `"E"`. | *(none)* | `E` | *(none)* |
| `Street_PostDirectional` | e.g. `"N"` or `"South"` (both accepted). | `South` | *(none)* | *(none)* |
| `Street_PostType` | e.g. `"St"` or `"Drive"`. | *(none)* | `St` | `Drive` |

Whenever `Street_PreDirectional` / `Street_PostDirectional` / `Street_PostType`
are explicitly supplied, they take precedence over whatever `PrimaryName`
parsing detected on its own -- so example 2's `PrimaryName` of `"E Main St"`
together with its own `Street_PreDirectional` of `"E"` and `Street_PostType`
of `"St"` is handled exactly the same as if `PrimaryName` had just been the
bare word `"Main"`.

**Secondary/unit address, independent of the above.** Follows the same
combined-vs-split pattern; none of the three worked examples has a
secondary unit, so see the "Other examples" table below instead.

| Parameter | Meaning |
| --- | --- |
| `AddressSecondaryAddress` | A combined secondary/unit address, e.g. `"Apt 1"`. Highest priority for the secondary address; if set, the two parameters below are ignored. |
| `AddressSecondaryAbbreviation` | e.g. `"Apt"`. |
| `AddressSecondaryNumber_LowRange` | Low end of a secondary-unit number range, in its own column; used when `AddressSecondaryAddress` is blank. |
| `AddressSecondaryNumber_HighRange` | High end of that same range, in a second, separate column. |

**Output.**

| Parameter | Meaning |
| --- | --- |
| `OutputAttributePrefix` | Optional prefix applied to every attribute this transformer writes back (e.g. `MAIL_`), useful if the same transformer runs more than once in one workspace against different address roles. |

A feature type with none of these configured simply yields an empty result
-- never an error. The transformer writes back `full_address_caps`,
`full_address_title`, and every key from `standardize_address()`'s
`parsed_segments` (optionally prefixed) onto each feature.

### Other examples

A few more combinations, to show individual fields in isolation:

| Scenario | Fields set | Result |
| --- | --- | --- |
| Full address with an embedded unit and a city/state/zip tail | `FullAddress="133 S Burlington St, Apt 4, South Burlington, VT 05403"` | `full_address_caps` = `133 SOUTH BURLINGTON STREET, UNIT 4` |
| Primary + secondary as two combined columns, with an output prefix | `PrimaryAddress="88 South Hill Rd"`, `AddressSecondaryAddress="Ste 2"`, `OutputAttributePrefix="MAIL_STD_"` | `MAIL_STD_full_address_caps` = `88 SOUTH HILL ROAD, UNIT 2` (every output attribute is prefixed with `MAIL_STD_`) |
| Address-number range (road-centerline segment) | `AddressNumber_LowRange="1"`, `AddressNumber_HighRange="5"`, `PrimaryName="Main St"` | `address_number_caps` = `1-5`, `full_address_caps` = `1-5 MAIN STREET` |
| Half-value number from a split `AddressNumber` + `AddressNumber_Suffix` | `AddressNumber="33"`, `AddressNumber_Suffix="1/2"`, `PrimaryName="Main St"` | `33 1/2 MAIN STREET` |
| Secondary unit from a split abbreviation + range | `AddressSecondaryAbbreviation="Apt"`, `AddressSecondaryNumber_LowRange="1"`, `AddressSecondaryNumber_HighRange="5"` | `secondary_address_caps` = `UNIT 1-5` |
| No address-role parameters set at all | *(nothing)* | Every output value is `None` -- never an error |

This module only standardizes address *numbers* and *street names*; it
never inspects or cleans city, state, or zip/zip+4 values, beyond
recognizing and discarding a trailing city/state/zip tail on `FullAddress`
so it doesn't get mistaken for part of the street.

The same logic is available outside of FME via
`standardize_feature_attributes(attributes, ...)`, which takes a plain
`dict` of attribute values and returns the flat output dict, for testing or
use in other pipelines.
