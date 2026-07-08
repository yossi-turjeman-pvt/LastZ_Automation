import cv2
import numpy as np

# Load common_bottom.png
im = cv2.imread("/Users/yossiturjeman/LastZ_Automation/templates/common_bottom.png")
h, w, c = im.shape

# Scan for green pixels only in the bottom bar region (Y > 150)
mask = (im[:, :, 1] > im[:, :, 2] + 30) & (im[:, :, 1] > im[:, :, 0] + 30)
# Zero out everything above Y = 150
mask[:150, :] = False

# Find coordinates of all matching pixels
y_indices, x_indices = np.where(mask)

if len(y_indices) > 0:
    min_y, max_y = np.min(y_indices), np.max(y_indices)
    min_x, max_x = np.min(x_indices), np.max(x_indices)
    print(f"Found green Claim All button bounds inside common_bottom.png:")
    print(f"X range: {min_x} to {max_x} (width={max_x - min_x})")
    print(f"Y range: {min_y} to {max_y} (height={max_y - min_y})")
    
    # Crop the button
    # Let's exclude the right side of the button to avoid the red badge (which is on the top right)
    # The badge is around the rightmost 40 pixels of the button.
    crop_btn = im[min_y:max_y, min_x + 10:max_x - 45]
    cv2.imwrite("/Users/yossiturjeman/LastZ_Automation/templates/claim_all_button_clean.png", crop_btn)
    print("Saved perfect green Claim All button template!")
else:
    print("No green pixels found in the bottom bar of common_bottom.png!")
