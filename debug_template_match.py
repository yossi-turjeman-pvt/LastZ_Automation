import cv2
import numpy as np

large_img = cv2.imread("/tmp/game_screen.png", cv2.IMREAD_GRAYSCALE)
template = cv2.imread("/Users/yossiturjeman/LastZ_Automation/templates/claim_button_clean.png", cv2.IMREAD_GRAYSCALE)

res = cv2.matchTemplate(large_img, template, cv2.TM_CCOEFF_NORMED)
min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)

print(f"DEBUG: Max similarity = {max_val:.4f}")
print(f"DEBUG: Match top-left = {max_loc}")

# Draw rectangle around match on a copy of large_img and save it
color_img = cv2.imread("/tmp/game_screen.png")
h, w = template.shape
top_left = max_loc
bottom_right = (top_left[0] + w, top_left[1] + h)
cv2.rectangle(color_img, top_left, bottom_right, (0, 255, 0), 2)
cv2.imwrite("/Users/yossiturjeman/LastZ_Automation/templates/debug_claim_match.png", color_img)

print("Saved debug match visualization!")
