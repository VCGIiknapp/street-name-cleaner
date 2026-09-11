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
```

`standardize_address()` returns:

```python
{
    "full_address_caps": "...",
    "parsed_segments": {
        "primary_address_caps": "...",
        "address_number_caps": "...",
        "prefix_directional_caps": "...",
        "street_name_caps": "...",
        "road_type_caps": "...",
        "suffix_directional_caps": "...",
        "secondary_address_caps": "...",
    },
}
```

Every value is ALL CAPS; there is no Title Case output.

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
the house number itself (rural VT camp/lot numbering, e.g. "H 5"). Every
address-role parameter below is optional and independent -- supply
whichever ones exist on a given feature type and leave the rest blank;
**there is no required combination.**

### Setting it up in a PythonCaller

A **PythonCaller** transformer's "Class to Process Features" parameter has
no dialog for a class's constructor arguments -- there's no auto-generated
per-parameter UI. Instead:

1. Add a **PythonCaller** transformer and set its **Class to Process
   Features** parameter to `AddressCleaner`.
2. Paste the script below directly into the PythonCaller's script editor.
3. Edit the quoted strings inside `DownloadedCleaner(...)` to your feature
   type's actual attribute names (leave any you don't need as `""`).

```python
import urllib.request
import sys
import types
import fme
import fmeobjects

# 1. Fetch the updated code from GitHub
GITHUB_RAW_URL = "https://raw.githubusercontent.com/VCGIiknapp/street-name-cleaner/master/street_name_cleaner.py"

try:
    response = urllib.request.urlopen(GITHUB_RAW_URL)
    script_code = response.read().decode('utf-8')
except Exception as e:
    raise RuntimeError(f"Failed to fetch street_name_cleaner.py from GitHub: {e}")

# 2. Load the downloaded code into memory
module_name = "street_name_cleaner"
dynamic_module = types.ModuleType(module_name)
sys.modules[module_name] = dynamic_module
exec(script_code, dynamic_module.__dict__)

# 3. Grab the downloaded class
DownloadedCleaner = dynamic_module.AddressCleaner

# 4. Create a local class that FME can use to map your granular attributes
class AddressCleaner(object):
    def __init__(self):
        # ========================================================
        # SET YOUR COLUMN NAMES HERE:
        # Put your exact FME attribute names inside the quotes.
        # Leave any that you don't need as empty strings ("").
        # ========================================================
        self.cleaner = DownloadedCleaner(
            FullAddress="",                      # Example: "SITE_ADDRESS"
            PrimaryAddress="",
            PrimaryName="",                      # Example: "STREET_NAME"
            AddressNumber="",                    # Example: "HOUSE_NUM"
            AddressNumber_LowRange="",
            AddressNumber_HighRange="",
            AddressNumber_Prefix="",
            AddressNumber_Suffix="",
            Street_PreDirectional="",            # Example: "PRE_DIR"
            Street_PostDirectional="",
            Street_PostType="",                  # Example: "ROAD_TYPE"
            AddressSecondaryAddress="",          # Example: "APT_UNIT"
            AddressSecondaryAbbreviation="",
            AddressSecondaryNumber_LowRange="",
            AddressSecondaryNumber_HighRange="",
            OutputAttributePrefix="CLEAN_"       # (Optional) e.g., creates "CLEAN_full_address_caps"
        )

    def input(self, feature):
        self.cleaner.input(feature)

    def close(self):
        self.cleaner.close()
```

Because the repo is **private**, this only works if the FME engine running
the workspace can authenticate to GitHub (e.g. a token embedded in the URL
or a network/proxy configuration that already has access) -- a plain
anonymous `urllib.request.urlopen()` against a private repo's raw URL will
fail with an HTTP 404. If that's not set up, an equally valid alternative is
to skip the download step entirely: copy `street_name_cleaner.py` onto the
FME engine's Python path (or alongside the workspace) and `import
street_name_cleaner` normally in step 2-3 above instead of fetching it from
GitHub.

Fetching the module fresh from GitHub on every run means workspaces always
pick up the latest version of the standardization rules without needing to
be edited -- but it also means a run's behavior can change if the repo
changes underneath it and there's no version pinning. Pin to a specific
commit SHA in `GITHUB_RAW_URL` (instead of `master`) if you need a
workspace's behavior to stay fixed over time.

### Worked examples

The three examples below are used consistently throughout this section --
example 1, 2, and 3 always refer to the same three real-world features:

1. A rural VT Route address: **`2729 VT Route 114 S, Norton, VT 05907`**
2. An in-town address: **`137 E Main St, Hyde Park, VT 05655`**
3. A camp/lot address with a house-number prefix: **`H 5 Stonehedge Dr, South Burlington, VT 05403`**

All three clean to the same result: `2729 VT ROUTE 114 S`, `137 EAST MAIN
STREET`, and `H5 STONEHEDGE DRIVE`, respectively. **How that result is
returned depends on which tier of input was used:**

| Example | Tier 1 (`FullAddress`/`PrimaryAddress`) `full_address_caps` | Tier 2 (building blocks) individual segments |
| --- | --- | --- |
| 1 | `2729 VT ROUTE 114 S` | `address_number_caps`=`2729`, `street_name_caps`=`VT ROUTE 114`, `suffix_directional_caps`=`S` |
| 2 | `137 EAST MAIN STREET` | `address_number_caps`=`137`, `prefix_directional_caps`=`EAST`, `street_name_caps`=`MAIN`, `road_type_caps`=`STREET` |
| 3 | `H5 STONEHEDGE DRIVE` | `address_number_caps`=`H5`, `street_name_caps`=`STONEHEDGE`, `road_type_caps`=`DRIVE` |

Tier 1 produces one combined `full_address_caps` (and `primary_address_caps`)
attribute because a combined address was actually given as input. Tier 2
never fabricates those combined attributes -- see "Outputs are only a
direct cleaning of whatever was actually supplied" below.

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

**A word that's also a valid road type isn't always one.** Words like
"Hill", "Lake", and "Mill" are legitimate road types on their own (e.g.
"Blue Spruce Hill") but just as often are part of a street's actual name
(e.g. "Canaan Hill Rd", where "Hill" belongs to the name and "Rd" is the
real road type). When `Street_PostType` is supplied, `PrimaryName`'s
trailing word is only treated as a redundant, droppable road type if it
actually matches `Street_PostType` (as with `"St"`/`"St"` above);
otherwise it's assumed to be part of the name and kept:

| `PrimaryName` | `Street_PostType` | Result |
| --- | --- | --- |
| `Canaan Hill` | `Rd` | `street_name_caps` = `CANAAN HILL`, `road_type_caps` = `ROAD` |
| `Lake Morey` | `Rd` | `street_name_caps` = `LAKE MOREY`, `road_type_caps` = `ROAD` |
| `E Main St` | `St` | `street_name_caps` = `MAIN`, `road_type_caps` = `STREET` (redundant `St` dropped) |

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
-- never an error.

**Outputs are only a direct cleaning of whatever was actually supplied.**
The combined `full_address_caps` / `primary_address_caps` attributes are
only written back when `FullAddress` or `PrimaryAddress` was itself given --
since only then is there an actual combined address being cleaned, rather
than one invented out of unrelated individual fields. When only
building-block fields (Tier 2) are supplied, the transformer writes back
only the individual cleaned segments that correspond to what was given
(`address_number_caps`, `prefix_directional_caps`, `street_name_caps`,
`road_type_caps`, `suffix_directional_caps`, and/or `secondary_address_caps`)
-- it never fabricates a `full_address_caps` or `primary_address_caps` out
of them. All output attribute names are optionally prefixed with
`OutputAttributePrefix`.

### Other examples

A few more combinations, to show individual fields in isolation:

| Scenario | Fields set | Result |
| --- | --- | --- |
| Full address with an embedded unit and a city/state/zip tail | `FullAddress="133 S Burlington St, Apt 4, South Burlington, VT 05403"` | `full_address_caps` = `133 SOUTH BURLINGTON STREET, UNIT 4` (Tier 1 -- combined keys are produced) |
| Primary + secondary as two combined columns, with an output prefix | `PrimaryAddress="88 South Hill Rd"`, `AddressSecondaryAddress="Ste 2"`, `OutputAttributePrefix="MAIL_STD_"` | `MAIL_STD_full_address_caps` = `88 SOUTH HILL ROAD, UNIT 2` (every output attribute is prefixed with `MAIL_STD_`) |
| Address-number range (road-centerline segment), building blocks only | `AddressNumber_LowRange="1"`, `AddressNumber_HighRange="5"`, `PrimaryName="Main St"` | `address_number_caps` = `1-5`, `street_name_caps` = `MAIN`, `road_type_caps` = `STREET` -- no `full_address_caps` or `primary_address_caps` key at all (Tier 2 -- no combined input was given) |
| Half-value number from a split `AddressNumber` + `AddressNumber_Suffix` | `AddressNumber="33"`, `AddressNumber_Suffix="1/2"`, `PrimaryName="Main St"` | `address_number_caps` = `33 1/2` -- again, no combined key |
| Secondary unit from a split abbreviation + range | `AddressSecondaryAbbreviation="Apt"`, `AddressSecondaryNumber_LowRange="1"`, `AddressSecondaryNumber_HighRange="5"` | `secondary_address_caps` = `UNIT 1-5` |
| No address-role parameters set at all | *(nothing)* | Every segment value is `None`, and no combined keys are present at all -- never an error |

This module only standardizes address *numbers* and *street names*; it
never inspects or cleans city, state, or zip/zip+4 values, beyond
recognizing and discarding a trailing city/state/zip tail on `FullAddress`
so it doesn't get mistaken for part of the street.

The same logic is available outside of FME via
`standardize_feature_attributes(attributes, ...)`, which takes a plain
`dict` of attribute values and returns the flat output dict, for testing or
use in other pipelines.
