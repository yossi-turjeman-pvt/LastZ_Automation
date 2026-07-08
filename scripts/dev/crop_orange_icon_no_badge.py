from PIL import Image

im = Image.open("/Users/yossiturjeman/LastZ_Automation/templates/orange_badge_icon_clean.png")
# Crop only the center/left gold chest area, excluding the red circle badge on the top right
# orange_badge_icon_clean.png is 120 x 120
box = (15, 30, 85, 110)
cropped = im.crop(box)
cropped.save("/Users/yossiturjeman/LastZ_Automation/templates/orange_icon_no_badge.png")

print("Cropped clean orange badge icon template (excluding badge) successfully!")
