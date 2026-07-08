import cv2
import numpy as np

# Load /tmp/game_screen.png (where ONLY the Alliance Menu is open)
im = cv2.imread("/tmp/game_screen.png")
h, w, c = im.shape

# Scan the left side of the bottom bar for the circular back arrow
# The arrow is white, so it has high values in R, G, B channels
# We'll scan relative Y: 1700 to 1950 physical pixels
# And horizontally around X: 1100 to 1350 physical pixels
mask = (im[:, :, 0] > 200) & (im[:, :, 1] > 200) & (im[:, :, 2] > 200)
mask[:1700, :] = False
mask[1950:, :] = False
mask[:, :1100] = False
mask[:, 1350:] = False

y_indices, x_indices = np.where(mask)

if len(y_indices) > 0:
    min_y, max_y = np.min(y_indices), np.max(y_indices)
    min_x, max_x = np.min(x_indices), np.max(x_indices)
    center_x = (min_x + max_x) // 2
    center_y = (min_y + max_y) // 2
    
    print(f"Found Alliance Menu Back Arrow at physical: X={center_x}, Y={center_y}")
    print(f"Logical coordinates (Retina 2x): X={center_x / 2:.2f}, Y={center_y / 2:.2f}")
else:
    print("Could not find white back arrow pixels on the Alliance Menu bottom bar.")
