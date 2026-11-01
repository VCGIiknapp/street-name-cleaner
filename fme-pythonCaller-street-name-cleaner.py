import urllib.request
import sys
import types
import fme
import fmeobjects

# 1. Fetch the updated code from GitHub
GITHUB_RAW_URL = "https://raw.githubusercontent.com/VCGIiknapp/street-name-cleaner/master/street-name-cleaner.py"

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

# 4. Create a local class that INHERITS from the downloaded script.
class AddressCleaner(DownloadedCleaner):
    def __init__(self):
        """
        ===========================================================================
        SET YOUR COLUMN NAMES HERE
        ===========================================================================
        Map your FME attribute names (as strings) to the parameters below.
        Leave the string empty ("") for any attributes you don't have.

        HOW THESE ARE COMBINED (decided per feature, not per workspace):
        The GRANULAR fields below (AddressNumber, PrimaryName/StreetName,
        Street_PreDirectional, Street_PostDirectional, Street_PostType) are
        always used first, wherever you've populated them -- they're the more
        authoritative signal, since there's no guesswork left once a role is
        already split into its own column. FullAddress/PrimaryAddress is only
        used to fill in whichever of those segments the granular fields left
        blank for that particular feature (e.g. a road type that's present in
        the combined text but missing from a bare StreetName column with
        nowhere else to put it).

        That means it's safe -- and usually worth it -- to configure BOTH a
        combined column and the granular fields at the same time, even if
        neither is complete on its own for every record: each feature gets
        whichever pieces its own granular fields have, with the combined
        column automatically patching in anything still missing on that same
        feature. If you only have one or the other, that's fine too --
        configure just what you have and leave the rest blank.

        EXAMPLE OF ADDRESS PARTS:
        FullAddress:             "137 E Main St, Hyde Park, VT 05655"
        PrimaryAddress:          "137 E Main St"
        AddressNumber:           "137"
        PrimaryName:             "E Main St"
        Street_PreDirectional:   "E"
        StreetName:              "Main"
        Street_PostType:         "ST"
        Street_PostDirectional:  "n/a"
        ===========================================================================
        """
        super().__init__(
            # --- GRANULAR FIELDS: used first, wherever populated ---
            # Best if you have the number and the full street name already separated.
            # You must use both AddressNumber and PrimaryName together.
            AddressNumber="",
            PrimaryName="",

            # Use these if you don't have PrimaryName, but have the street parts.
            # You must use AddressNumber and all of these columns together
            # (if there's no PrimaryName).
            StreetName="",
            Street_PreDirectional="",
            Street_PostDirectional="",
            Street_PostType="",

            # --- COMBINED FIELDS: fill in whatever the granular fields above left blank ---
            # Safe to set alongside the granular fields above -- only patches
            # gaps on a feature-by-feature basis, never overrides a granular
            # field that's already populated. You only need to provide either
            # PrimaryAddress or FullAddress, not both.
            PrimaryAddress="",
            FullAddress="",

            # --- ADDITIONAL ADDRESS NUMBER MODIFIERS ---
            # If your dataset provides address number modifiers as separate columns,
            # you can provide them here.
            AddressNumber_Prefix="",
            AddressNumber_Suffix="",
            # If your dataset does not provide a single AddressNumber, but instead presents data as a
            # two-column range of address numbers, you can provide them here.
            # Leave these blank if you're using AddressNumber.
            AddressNumber_LowRange="",
            AddressNumber_HighRange="",
            # If your dataset does not provide a single AddressNumber or a 2-column range, but instead presents
            # a 2-column address number range per side of the street, you may provide those 4 columns here.
            # Leave these blank if you're using AddressNumber of AddressNumber_LowRange/
            # HighRange instead.
            AddressNumber_LowRange_Left="",
            AddressNumber_HighRange_Left="",
            AddressNumber_LowRange_Right="",
            AddressNumber_HighRange_Right="",

            # --- SECONDARY ADDRESS INFO (Units, Suites, etc.) ---
            # Same granular-first, combined-fills-gaps rule applies here: if
            # these are blank, a secondary/unit address embedded in
            # FullAddress/PrimaryAddress (e.g. "Apt 4") is still picked up
            # automatically -- unless that combined text also failed to find
            # an address number on its own, in which case its secondary-unit
            # reading is untrustworthy too (e.g. a "#" that's actually part
            # of a lot number, not a unit) and is skipped rather than risk
            # double-counting the same digits.
            AddressSecondaryAddress="",
            AddressSecondaryAbbreviation="",
            # If your dataset does not provide a single AddressSecondaryNumber, but instead presents data as a
            # two-column range of secondary address numbers, you can provide them here.
            AddressSecondaryNumber_LowRange="",
            AddressSecondaryNumber_HighRange="",
        )

    def input(self, feature):
        # Passes the FME feature to the parent class for processing
        super().input(feature)

    def close(self):
        # Ensures clean breakdown if the parent class uses it
        if hasattr(super(), 'close'):
            super().close()