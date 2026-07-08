from PIL import Image

im = Image.open("/Users/yossiturjeman/LastZ_Automation/templates/bottom_right_menu.png")

# Shifting X to the right and Y down to center the shield
# Let's crop 100x100
box = (90, 165, 190, 265)
cropped = im.crop(box)
cropped.save("/Users/yossiturjeman/LastZ_Automation/templates/alliance_shield.png")

print("Alliance shield candidate precisely cropped!")
