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
        
        PERFORMANCE & ACCURACY NOTES:
        - TIER 1 (Best): Provide `AddressNumber` + `PrimaryName`.
        - TIER 2 (Good): Provide `AddressNumber` + Subparts (`StreetName`, 
                         `Street_PreDirectional`, etc.).
        - TIER 3 (Least Preferred): Provide `PrimaryAddress` or `FullAddress`. 
                         This forces the script to parse the string and make 
                         assumptions that may be incorrect.
                         
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
            # --- TIER 1: MOST EFFICIENT ---
            # Best if you have the number and the full street name already separated.
            # You must use both AddressNumber and PrimaryName together.
            AddressNumber="", 
            PrimaryName="", 
            
            # --- TIER 2: ALTERNATIVE EFFICIENT ---
            # Use these if you don't have PrimaryName, but have the street parts.
            # You must use AddressNumber and all of the tier 2 columns together
            # (if there's no PrimaryName).
            StreetName="", 
            Street_PreDirectional="",            
            Street_PostDirectional="",
            Street_PostType="",                  
            
            # --- TIER 3: LEAST PREFERRED (Forces script parsing) ---
            # Use only if your data is unsegmented and the previous 2 tiers can't be completed.
            # You only need to provide either PrimaryAddress or FullAddress, not both.
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