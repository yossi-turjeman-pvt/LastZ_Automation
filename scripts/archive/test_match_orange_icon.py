import cv2
import numpy as np

large_img = cv2.imread("/tmp/game_screen.png", cv2.IMREAD_GRAYSCALE)
template = cv2.imread("/Users/yossiturjeman/LastZ_Automation/templates/orange_icon_no_badge.png", cv2.IMREAD_GRAYSCALE)

res = cv2.matchTemplate(large_img, template, cv2.TM_CCOEFF_NORMED)
min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)

print(f"Max match similarity of 'Orange Icon': {max_val:.4f}")
if max_val > 0.8:
    h, w = template.shape
    top_left = max_loc
    # We want to click at the center of the full 120x120 button, which is slightly to the right and top of this cropped template
    # Let's adjust offset relative to top-left of this cropped template
    # Relative to top-left (min_x, min_y):
    # center is around top_left + (w/2 + 20, h/2 - 10) physical pixels.
    center_x = top_left[0] + w // 2 + 20
    center_y = top_left[1] + h // 2 - 10
    print(f"Found 'Orange Icon' center at physical: X={center_x}, Y={center_y}")
    print(f"Logical coordinates (Retina 2x): X={center_x / 2:.2f}, Y={center_y / 2:.2f}")
else:
    print("Could not find 'Orange Icon' template.")
