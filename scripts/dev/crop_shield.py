from PIL import Image

# Open the bottom_right_menu.png (size 204 x 600)
im = Image.open("/Users/yossiturjeman/LastZ_Automation/templates/bottom_right_menu.png")

# Let's crop a candidate of 100x100 for the Alliance shield icon
# Let's guess the shield is centered horizontally at 105, vertically around 190
# X from 55 to 155, Y from 135 to 235
box1 = (55, 135, 155, 235)
cropped1 = im.crop(box1)
cropped1.save("/Users/yossiturjeman/LastZ_Automation/templates/alliance_shield.png")

print("Alliance shield candidate cropped!")
