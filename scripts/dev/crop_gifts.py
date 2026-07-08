from PIL import Image

# Open the alliance_popup.png (cropped at X=400, Y=300, size 2200 x 1300)
im = Image.open("/Users/yossiturjeman/LastZ_Automation/templates/alliance_popup.png")

# Let's crop a box where the Alliance Gifts button resides
# Let's try X offset from 1000 to 1500, Y offset from 700 to 900
box = (1000, 700, 1500, 900)
cropped = im.crop(box)
cropped.save("/Users/yossiturjeman/LastZ_Automation/templates/gifts_button_area.png")

print("Alliance Gifts button area cropped!")
