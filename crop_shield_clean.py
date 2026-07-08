from PIL import Image

im = Image.open("/Users/yossiturjeman/LastZ_Automation/templates/alliance_shield.png")
# Crop center of the shield to avoid the badge
# Image is 100x100
box = (15, 20, 75, 80)
cropped = im.crop(box)
cropped.save("/Users/yossiturjeman/LastZ_Automation/templates/alliance_shield_clean.png")

print("Clean Alliance shield template cropped successfully!")
