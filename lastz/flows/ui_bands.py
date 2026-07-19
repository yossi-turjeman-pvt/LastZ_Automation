"""
UI spatial bands as fractions of the full capture (or game ROI) size.

Tuned from vision scout dumps on 14" (3024x1964): Alliance grid tiles ~yf 0.50–0.70;
HUD shield sits in the lower-right stack; gifts Common/Rare tabs sit under the
chest/Level bar (~yf 0.40–0.45), NOT in the modal header (old band caused FPs).
"""

# (y0, y1, x0, x1)
BAND_RARE_TAB = (0.35, 0.52, 0.40, 0.72)
BAND_ALLIANCE_GRID = (0.40, 0.78, 0.15, 0.85)
BAND_TECH_TREE = (0.12, 0.72, 0.18, 0.82)
BAND_HUD_SHIELD = (0.55, 0.95, 0.72, 1.0)
# Gift-list Claims sit ~yf 0.50–0.80; footer/back icon is lower (~yf 0.85+).
# 0.48 was too tight and dropped every real list Claim after Rare switch.
CLAIM_MAX_Y_FRAC = 0.82
