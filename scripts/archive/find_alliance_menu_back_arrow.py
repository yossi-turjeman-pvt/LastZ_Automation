import cv2
import numpy as np

# Load the full screen Alliance menu bottom crop (physical X: 0 to 3024, Y: 1600 to 1964)
im = cv2.imread("/Users/yossiturjeman/LastZ_Automation/templates/alliance_menu_bottom.png")
h, w, c = im.shape

# Let's find the white back arrow pixels inside the grey circle
# The back arrow is white, so it has high values in R, G, B channels (e.g. R > 200, G > 200, B > 200)
# It is located around Y = 1750 to 1850 physical (which inside our crop is Y = 150 to 250)
# And horizontally it should be on the left side of the menu (around X = 1000 to 1200)
mask = (im[:, :, 0] > 200) & (im[:, :, 1] > 200) & (im[:, :, 2] > 200)
# Limit to relative Y: 140 to 250, and X: 1000 to 1300
mask[:140, :] = False
mask[250:, :] = False
mask[:, :1000] = False
mask[:, 1300:] = False

y_indices, x_indices = np.where(mask)

if len(y_indices) > 0:
    min_y, max_y = np.min(y_indices), np.max(y_indices)
    min_x, max_x = np.min(x_indices), np.max(x_indices)
    center_x = (min_x + max_x) // 2
    # Convert relative Y to screen absolute Y (starts at 1600)
    center_y = 1600 + (min_y + max_y) // 2
    
    print(f"Found Back Arrow at physical: X={center_x}, Y={center_y}")
    print(f"Logical coordinates (Retina 2x): X={center_x / 2:.2f}, Y={center_y / 2:.2f}")
else:
    print("Could not find white back arrow pixels in the search range.")
